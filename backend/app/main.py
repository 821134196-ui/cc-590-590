"""FastAPI 主应用：授权、背调发起/回传、三级结果权限、异常、更正、封存、时间线、访问记录。"""
import secrets
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import get_db, engine, Base
from . import schemas, security
from .catalog import CHECK_ITEMS
from .models import (
    User, Agency, Consent, CheckRequest, CheckResult, Anomaly,
    CorrectionRequest, ResultAmendment, AccessLog, TimelineEvent, Notification,
    utcnow,
)
from .seed import seed
from .services import notify, log_event

app = FastAPI(title="企业招聘背调授权与结果封存系统", version="1.0")


# ---------------------------------------------------------------- 启动

@app.on_event("startup")
def _startup():
    Base.metadata.create_all(engine)
    from .database import SessionLocal
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@app.exception_handler(security.RuleError)
def rule_error_handler(_request, exc: security.RuleError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


# ---------------------------------------------------------------- 当前用户（本地模拟登录）

def current_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    if x_user_id is None:
        raise HTTPException(401, "缺少 X-User-Id（本地模拟登录）")
    user = db.get(User, x_user_id)
    if not user or not user.active:
        raise HTTPException(401, "用户不存在或已停用")
    return user


# ---------------------------------------------------------------- 序列化

def user_brief(u: User | None) -> dict | None:
    if not u:
        return None
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role}


def consent_dict(c: Consent, db: Session) -> dict:
    viewers = [db.get(User, i) for i in (c.viewer_ids or [])]
    return {
        "id": c.id,
        "code": c.code,
        "candidate": user_brief(db.get(User, c.candidate_id)),
        "recruiter": user_brief(db.get(User, c.recruiter_id)),
        "position": c.position,
        "approved_items": c.approved_items,
        "approved_item_labels": [CHECK_ITEMS[i]["label"] for i in c.approved_items if i in CHECK_ITEMS],
        "viewers": [user_brief(v) for v in viewers if v],
        "granted_at": c.granted_at,
        "expires_at": c.expires_at,
        "status": c.status,
        "withdrawn_at": c.withdrawn_at,
        "withdraw_reason": c.withdraw_reason,
        "cancelled_at": c.cancelled_at,
        "cancel_reason": c.cancel_reason,
        "active": security.consent_is_active(c),
    }


def check_brief(chk: CheckRequest, db: Session) -> dict:
    consent = chk.consent
    return {
        "id": chk.id,
        "code": chk.code,
        "consent_id": chk.consent_id,
        "consent_code": consent.code,
        "candidate_name": db.get(User, consent.candidate_id).display_name,
        "position": consent.position,
        "requester": user_brief(db.get(User, chk.requester_id)),
        "agency": {"id": chk.agency_id, "name": db.get(Agency, chk.agency_id).name},
        "requested_items": chk.requested_items,
        "requested_item_labels": [CHECK_ITEMS[i]["label"] for i in chk.requested_items if i in CHECK_ITEMS],
        "status": chk.status,
        "seal_reason": chk.seal_reason,
        "created_at": chk.created_at,
        "sealed_at": chk.sealed_at,
        "viewer_ids": consent.viewer_ids or [],
        "has_result": any(not r.is_duplicate for r in chk.results),
        "duplicate_count": sum(1 for r in chk.results if r.is_duplicate),
        "pending_anomalies": sum(1 for a in chk.anomalies if a.status == "pending"),
    }


def get_check_or_404(db: Session, check_id: int) -> CheckRequest:
    chk = db.get(CheckRequest, check_id)
    if not chk:
        raise HTTPException(404, "背调请求不存在")
    return chk


def seal_check(db: Session, chk: CheckRequest, reason: str):
    if chk.status != "sealed":
        chk.status = "sealed"
        chk.sealed_at = utcnow()
        chk.seal_reason = reason
        log_event(db, "check_sealed", request_id=chk.id, consent_id=chk.consent_id,
                  detail={"reason": reason})


# ---------------------------------------------------------------- 基础数据

@app.get("/api/users")
def list_users(db: Session = Depends(get_db)):
    return [user_brief(u) for u in db.query(User).filter_by(active=True).order_by(User.id)]


@app.get("/api/agencies")
def list_agencies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Agency).filter_by(active=True)
    if user.role == "agency":
        q = q.filter(Agency.id == user.agency_id)
    return [{"id": a.id, "name": a.name, "contact": a.contact} for a in q]


@app.get("/api/catalog")
def get_catalog():
    return CHECK_ITEMS


# ---------------------------------------------------------------- 授权

@app.post("/api/consents", status_code=201)
def create_consent(body: schemas.ConsentCreate, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    security.assert_can_create_consent(user)
    candidate = db.get(User, body.candidate_id)
    if not candidate or candidate.role != "candidate":
        raise security.RuleError("BAD_CANDIDATE", "候选人无效", http_status=422)
    if body.recruiter_id != user.id:
        raise security.RuleError("FORBIDDEN", "招聘专员只能以本人名义拟定授权")
    unknown = [i for i in body.approved_items if i not in CHECK_ITEMS]
    if unknown:
        raise security.RuleError("UNKNOWN_ITEM", f"未知调查项目：{unknown}", http_status=422)
    viewers = db.query(User).filter(User.id.in_(body.viewer_ids)).all() if body.viewer_ids else []
    bad = [v.display_name for v in viewers if v.role not in ("compliance", "recruiter")]
    if bad:
        raise security.RuleError("BAD_VIEWER", f"可见人只能是招聘/合规人员：{bad}", http_status=422)

    consent = Consent(
        code=f"CNS-{secrets.token_hex(4).upper()}",
        candidate_id=body.candidate_id,
        recruiter_id=body.recruiter_id,
        position=body.position,
        approved_items=body.approved_items,
        viewer_ids=[v.id for v in viewers],
        consent_text_snapshot=body.consent_text,
        expires_at=utcnow() + timedelta(days=body.valid_days),
    )
    db.add(consent)
    db.flush()
    log_event(db, "consent_granted", consent_id=consent.id, actor_id=candidate.id,
              detail={"position": body.position, "approved_items": body.approved_items,
                      "viewer_ids": body.viewer_ids, "valid_days": body.valid_days})
    notify(db, body.candidate_id, "授权已生效",
           f"您已授权《{body.position}》岗位背调，有效期 {body.valid_days} 天。")
    db.commit()
    db.refresh(consent)
    return consent_dict(consent, db)


@app.get("/api/consents")
def list_consents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Consent)
    if user.role == "candidate":
        q = q.filter_by(candidate_id=user.id)
    elif user.role == "recruiter":
        q = q.filter_by(recruiter_id=user.id)
    # compliance 可见全部
    return [consent_dict(c, db) for c in q.order_by(Consent.id.desc())]


@app.get("/api/consents/{consent_id}")
def get_consent(consent_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consent, consent_id)
    if not c:
        raise HTTPException(404, "授权不存在")
    if user.role not in ("compliance",) and user.id not in (c.candidate_id, c.recruiter_id):
        raise security.RuleError("FORBIDDEN", "无权查看该授权")
    return consent_dict(c, db)


@app.post("/api/consents/{consent_id}/withdraw")
def withdraw_consent(consent_id: int, body: schemas.ConsentWithdraw,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consent, consent_id)
    if not c:
        raise HTTPException(404, "授权不存在")
    security.assert_can_withdraw(user, c)
    if c.status != "granted":
        raise security.RuleError("CONSENT_NOT_GRANTED", f"授权当前状态为 {c.status}，无法撤回")
    c.status = "withdrawn"
    c.withdrawn_at = utcnow()
    c.withdraw_reason = body.reason
    # 撤回后：不得再发起新查询（发起接口拦截）；已有结果按权限封存
    log_event(db, "consent_withdrawn", consent_id=c.id, actor_id=user.id,
              detail={"reason": body.reason, "sealed": [chk.id for chk in c.checks]})
    for chk in c.checks:
        seal_check(db, chk, "候选人撤回授权，结果封存")
        notify(db, chk.requester_id, "背调结果已封存",
               f"候选人已撤回授权，背调单 {chk.code} 的结果已封存。")
    notify(db, c.recruiter_id, "候选人撤回背调授权",
           f"《{c.position}》候选人已撤回授权，不得再发起新查询。")
    db.commit()
    return {"ok": True, "message": "授权已撤回，已有结果已封存"}


@app.post("/api/consents/{consent_id}/cancel-position")
def cancel_position(consent_id: int, body: schemas.PositionCancel,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consent, consent_id)
    if not c:
        raise HTTPException(404, "授权不存在")
    security.assert_can_cancel_position(user, c)
    if c.status == "position_cancelled":
        raise security.RuleError("ALREADY_CANCELLED", "岗位已处于取消状态")
    c.status = "position_cancelled"
    c.cancelled_at = utcnow()
    c.cancel_reason = body.reason
    log_event(db, "position_cancelled", consent_id=c.id, actor_id=user.id,
              detail={"reason": body.reason})
    for chk in c.checks:
        seal_check(db, chk, "岗位取消，调查结果封存")
    notify(db, c.candidate_id, "岗位已取消", f"《{c.position}》岗位已取消，相关背调结果已封存。")
    db.commit()
    return {"ok": True, "message": "岗位已取消，相关调查与结果封存保留"}


# ---------------------------------------------------------------- 背调发起

@app.post("/api/checks", status_code=201)
def create_check(body: schemas.CheckCreate, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    consent = db.get(Consent, body.consent_id)
    if not consent:
        raise HTTPException(404, "授权不存在")
    agency = db.get(Agency, body.agency_id)
    if not agency or not agency.active:
        raise security.RuleError("BAD_AGENCY", "合作机构无效", http_status=422)

    # 核心拦截：超范围 / 撤回 / 到期 / 岗位取消 / 非本人授权
    security.assert_can_initiate_check(user, consent, body.requested_items)

    chk = CheckRequest(
        code=f"CHK-{secrets.token_hex(4).upper()}",
        consent_id=consent.id,
        requester_id=user.id,
        agency_id=agency.id,
        requested_items=body.requested_items,
    )
    db.add(chk)
    db.flush()
    log_event(db, "check_initiated", request_id=chk.id, consent_id=consent.id, actor_id=user.id,
              detail={"items": body.requested_items, "agency_id": agency.id, "reason": body.reason})
    agency_op = db.query(User).filter_by(role="agency", agency_id=agency.id).first()
    notify(db, agency_op.id if agency_op else None, "新背调任务",
           f"背调单 {chk.code}（{consent.position}）已下发，请在授权期限内回传结果。")
    db.commit()
    db.refresh(chk)
    return check_brief(chk, db)


@app.get("/api/checks")
def list_checks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(CheckRequest).join(Consent, CheckRequest.consent_id == Consent.id)
    if user.role == "candidate":
        q = q.filter(Consent.candidate_id == user.id)
    elif user.role == "recruiter":
        q = q.filter(CheckRequest.requester_id == user.id)
    elif user.role == "agency":
        q = q.filter(CheckRequest.agency_id == user.agency_id)
    return [check_brief(c, db) for c in q.order_by(CheckRequest.id.desc())]


# ---------------------------------------------------------------- 结果回传

@app.post("/api/checks/result")
def submit_result(body: schemas.ResultSubmit, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    chk = db.query(CheckRequest).filter_by(code=body.check_code).first()
    if not chk:
        raise HTTPException(404, "背调单不存在")
    security.assert_can_submit_result(user, chk)
    if chk.status == "sealed":
        raise security.RuleError("CHECK_SEALED", "该背调单已封存（授权撤回或岗位取消），不再接收回传")

    prior = [r for r in chk.results if not r.is_duplicate]
    is_dup = bool(prior)
    result = CheckResult(
        request_id=chk.id,
        agency_id=user.agency_id,
        payload=body.payload,
        raw_receipt=body.raw_receipt,
        is_duplicate=is_dup,
    )
    db.add(result)
    db.flush()
    if not is_dup:
        chk.status = "received"
        log_event(db, "result_received", request_id=chk.id, actor_id=user.id,
                  detail={"result_id": result.id, "items": list(body.payload.keys())})
        notify(db, chk.requester_id, "背调结果已回传", f"背调单 {chk.code} 结果已回传，默认脱敏展示。")
        notify(db, chk.consent.candidate_id, "背调结果已出具", f"背调单 {chk.code} 的结果已出具，您可在系统中查看。")
    else:
        # 重复回传：保留记录与时间线，但不覆盖原结果
        log_event(db, "result_duplicate", request_id=chk.id, actor_id=user.id,
                  detail={"result_id": result.id, "note": body.note,
                          "kept_original_result_id": prior[0].id})
        notify(db, chk.requester_id, "机构重复回传（已忽略）",
               f"背调单 {chk.code} 收到重复回传，系统保留原始结果并记录本次回传。")
    db.commit()
    return {
        "ok": True,
        "duplicate": is_dup,
        "message": "重复回传已登记但不覆盖原结果" if is_dup else "结果已接收",
        "result_id": result.id,
    }


def effective_result(chk: CheckRequest) -> CheckResult | None:
    """生效结果：最近一次非重复回传（更正叠加在其上）。"""
    normal = [r for r in chk.results if not r.is_duplicate]
    return normal[-1] if normal else None


def amendments_for(db: Session, result_id: int) -> list[ResultAmendment]:
    return db.query(ResultAmendment).filter_by(result_id=result_id).order_by(ResultAmendment.id).all()


def assert_sealed_access(user: User, consent: Consent, view: str):
    """封存后的访问限制：仅合规可继续查看；候选人本人仅可看脱敏版。"""
    if user.role == "compliance":
        return
    if user.id == consent.candidate_id and view == "masked":
        return
    raise security.RuleError("CHECK_SEALED", "结果已封存：仅合规人员可查看，候选人可查看本人脱敏结果")


@app.get("/api/checks/{check_id}/result")
def get_result(check_id: int, view: str = Query("masked", pattern="^(masked|full|raw)$"),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    chk = get_check_or_404(db, check_id)
    consent = chk.consent

    # 三级权限分别判定（含拒绝访问记录）
    try:
        security.assert_can_view(user, consent, chk, view)
    except security.RuleError as e:
        db.add(AccessLog(user_id=user.id, request_id=chk.id, target=view, granted=False,
                         denied_reason=e.code))
        db.commit()
        raise

    result = effective_result(chk)
    if not result:
        raise security.RuleError("NO_RESULT", "机构尚未回传结果", http_status=404)

    if chk.status == "sealed":
        assert_sealed_access(user, consent, view)

    target_map = {"masked": "masked_result", "full": "full_material", "raw": "raw_receipt"}
    amendments = amendments_for(db, result.id)
    effective_payload = security.apply_amendments(result.payload, amendments)

    if view == "raw":
        # 原始回执：每次查看都留痕
        db.add(AccessLog(user_id=user.id, request_id=chk.id, target="raw_receipt",
                         granted=True, reason="查看机构原始回执"))
        db.commit()
        return {
            "view": "raw",
            "result_id": result.id,
            "received_at": result.received_at,
            "is_duplicate": result.is_duplicate,
            "raw_receipt": result.raw_receipt,
            "amendments": [{"field_path": a.field_path, "new_value": a.new_value} for a in amendments],
        }

    unmask = view == "full"
    rendered, masked_fields = security.render_payload(effective_payload, chk.requested_items, unmask)
    db.add(AccessLog(
        user_id=user.id, request_id=chk.id, target=target_map[view], granted=True,
        masked_fields=[] if unmask else masked_fields,
        reason="查看完整材料（敏感字段明文）" if unmask else "查看脱敏结果",
    ))
    db.commit()

    return {
        "view": view,
        "result_id": result.id,
        "received_at": result.received_at,
        "sealed": chk.status == "sealed",
        "seal_reason": chk.seal_reason,
        "payload": rendered,
        "masked_fields": masked_fields,
        "amendments": [{"field_path": a.field_path, "old_value": a.old_value,
                        "new_value": a.new_value} for a in amendments],
        "duplicates": [
            {"result_id": r.id, "received_at": r.received_at}
            for r in chk.results if r.is_duplicate
        ],
    }


@app.get("/api/checks/{check_id}/timeline")
def get_timeline(check_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    chk = get_check_or_404(db, check_id)
    consent = chk.consent
    if (user.role not in ("compliance",)
            and user.id not in (consent.candidate_id, consent.recruiter_id, chk.requester_id)
            and not (user.role == "agency" and user.agency_id == chk.agency_id)):
        raise security.RuleError("FORBIDDEN", "无权查看该背调时间线")

    # 背调单自身事件 + 与该授权相关的状态事件（撤回/岗位取消）；
    # consent_granted 早于背调单创建，属于授权页信息，不计入背调单时间线。
    events = db.query(TimelineEvent).filter(
        (TimelineEvent.request_id == chk.id)
        | ((TimelineEvent.consent_id == consent.id)
           & (TimelineEvent.request_id.is_(None))
           & (TimelineEvent.event_type.in_(["consent_withdrawn", "position_cancelled"])))
    ).order_by(TimelineEvent.id).all()
    out = []
    for e in events:
        out.append({
            "id": e.id,
            "type": e.event_type,
            "actor": user_brief(db.get(User, e.actor_id)) if e.actor_id else None,
            "detail": e.detail,
            "created_at": e.created_at,
        })
    return out


# ---------------------------------------------------------------- 异常处理

@app.post("/api/anomalies", status_code=201)
def create_anomaly(body: schemas.AnomalyCreate, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    chk = get_check_or_404(db, body.check_id)
    security.assert_can_raise_anomaly(user)
    if not effective_result(chk):
        raise security.RuleError("NO_RESULT", "结果尚未回传，无法登记异常", http_status=422)
    anomaly = Anomaly(
        request_id=chk.id, raised_by_id=user.id, title=body.title,
        conclusion=body.conclusion, basis=body.basis, evidence_ref=body.evidence_ref,
    )
    db.add(anomaly)
    db.flush()
    log_event(db, "anomaly_raised", request_id=chk.id, actor_id=user.id,
              detail={"anomaly_id": anomaly.id, "title": body.title})
    for comp in db.query(User).filter_by(role="compliance", active=True).all():
        if comp.id != user.id:
            notify(db, comp.id, "待处理异常结论", f"背调单 {chk.code}：{body.title}")
    db.commit()
    db.refresh(anomaly)
    return {"ok": True, "id": anomaly.id}


@app.get("/api/anomalies")
def list_anomalies(status: str | None = None, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    q = db.query(Anomaly)
    if status:
        q = q.filter_by(status=status)
    rows = []
    for a in q.order_by(Anomaly.id.desc()):
        chk = a.request
        rows.append({
            "id": a.id,
            "check_id": chk.id,
            "check_code": chk.code,
            "candidate_name": db.get(User, chk.consent.candidate_id).display_name,
            "title": a.title,
            "conclusion": a.conclusion,
            "basis": a.basis,
            "evidence_ref": a.evidence_ref,
            "status": a.status,
            "raised_by": user_brief(db.get(User, a.raised_by_id)),
            "approver": user_brief(db.get(User, a.approver_id)) if a.approver_id else None,
            "decision_note": a.decision_note,
            "resolution": a.resolution,
            "decided_at": a.decided_at,
            "created_at": a.created_at,
        })
    return rows


@app.post("/api/anomalies/{anomaly_id}/decision")
def decide_anomaly(anomaly_id: int, body: schemas.AnomalyDecision,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Anomaly, anomaly_id)
    if not a:
        raise HTTPException(404, "异常记录不存在")
    if a.status != "pending":
        raise security.RuleError("ALREADY_DECIDED", "该异常已处理")
    # 必须合规，且不得批准自己提交的结论
    security.assert_can_decide_anomaly(user, a)
    a.status = "approved" if body.approve else "rejected"
    a.approver_id = user.id
    a.decision_note = body.decision_note
    a.resolution = body.resolution
    a.decided_at = utcnow()
    log_event(db, "anomaly_decided", request_id=a.request_id, actor_id=user.id,
              detail={"anomaly_id": a.id, "decision": a.status,
                      "resolution": body.resolution, "note": body.decision_note})
    notify(db, a.raised_by_id, "异常结论已处理",
           f"《{a.title}》已{'批准' if body.approve else '驳回'}。")
    db.commit()
    return {"ok": True, "status": a.status}


# ---------------------------------------------------------------- 候选人更正

@app.post("/api/corrections", status_code=201)
def create_correction(body: schemas.CorrectionCreate, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    chk = get_check_or_404(db, body.check_id)
    security.assert_can_create_correction(user, chk.consent)
    result = effective_result(chk)
    if not result:
        raise security.RuleError("NO_RESULT", "结果尚未回传", http_status=422)
    item, _, field = body.field_path.partition(".")
    if item not in chk.requested_items or not field:
        raise security.RuleError("BAD_FIELD", "更正字段不在本次调查范围内", http_status=422)
    cr = CorrectionRequest(
        request_id=chk.id, candidate_id=user.id, field_path=body.field_path,
        claimed_value=body.claimed_value, reason=body.reason,
    )
    db.add(cr)
    db.flush()
    log_event(db, "correction_requested", request_id=chk.id, actor_id=user.id,
              detail={"correction_id": cr.id, "field_path": body.field_path})
    for comp in db.query(User).filter_by(role="compliance", active=True).all():
        notify(db, comp.id, "候选人更正申请", f"背调单 {chk.code} 字段 {body.field_path} 申请更正。")
    db.commit()
    return {"ok": True, "id": cr.id}


@app.get("/api/corrections")
def list_corrections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(CorrectionRequest)
    if user.role == "candidate":
        q = q.filter_by(candidate_id=user.id)
    rows = []
    for cr in q.order_by(CorrectionRequest.id.desc()):
        rows.append({
            "id": cr.id,
            "check_id": cr.request_id,
            "check_code": cr.request.code,
            "field_path": cr.field_path,
            "claimed_value": cr.claimed_value,
            "reason": cr.reason,
            "status": cr.status,
            "candidate": user_brief(db.get(User, cr.candidate_id)),
            "handled_by": user_brief(db.get(User, cr.handled_by_id)) if cr.handled_by_id else None,
            "decision_note": cr.decision_note,
            "created_at": cr.created_at,
            "decided_at": cr.decided_at,
        })
    return rows


@app.post("/api/corrections/{correction_id}/decision")
def decide_correction(correction_id: int, body: schemas.CorrectionDecision,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    cr = db.get(CorrectionRequest, correction_id)
    if not cr:
        raise HTTPException(404, "更正申请不存在")
    security.assert_can_handle_correction(user)
    if cr.status != "pending":
        raise security.RuleError("ALREADY_DECIDED", "该更正申请已处理")
    chk = cr.request
    result = effective_result(chk)
    cr.status = "approved" if body.approve else "rejected"
    cr.handled_by_id = user.id
    cr.decision_note = body.decision_note
    cr.decided_at = utcnow()

    if body.approve:
        item, _, field = cr.field_path.partition(".")
        old = ""
        if result and isinstance(result.payload.get(item), dict):
            old = str(result.payload[item].get(field, ""))
        new_value = body.corrected_value or cr.claimed_value
        db.add(ResultAmendment(
            result_id=result.id, correction_id=cr.id, field_path=cr.field_path,
            old_value=old, new_value=new_value,
        ))
        log_event(db, "correction_approved", request_id=chk.id, actor_id=user.id,
                  detail={"correction_id": cr.id, "field_path": cr.field_path,
                          "old_value": old, "new_value": new_value})
        notify(db, cr.candidate_id, "更正申请已获批",
               f"字段 {cr.field_path} 已更正，原始记录保留，查看结果时以更正后内容为准。")
    else:
        log_event(db, "correction_rejected", request_id=chk.id, actor_id=user.id,
                  detail={"correction_id": cr.id, "note": body.decision_note})
        notify(db, cr.candidate_id, "更正申请未获批准", body.decision_note)
    db.commit()
    return {"ok": True, "status": cr.status}


# ---------------------------------------------------------------- 访问记录 / 通知

@app.get("/api/access-logs")
def list_access_logs(check_id: int | None = None, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    if user.role != "compliance":
        raise security.RuleError("FORBIDDEN", "只有合规人员可以查阅访问记录")
    q = db.query(AccessLog)
    if check_id:
        q = q.filter_by(request_id=check_id)
    rows = []
    for log in q.order_by(AccessLog.id.desc()).limit(500):
        rows.append({
            "id": log.id,
            "user": user_brief(db.get(User, log.user_id)),
            "check_code": db.get(CheckRequest, log.request_id).code,
            "target": log.target,
            "granted": log.granted,
            "denied_reason": log.denied_reason,
            "masked_fields": log.masked_fields,
            "reason": log.reason,
            "created_at": log.created_at,
        })
    return rows


@app.get("/api/notifications")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter_by(recipient_id=user.id).order_by(Notification.id.desc()).limit(100)
    return [{"id": n.id, "title": n.title, "content": n.content, "read": n.read,
             "channel": n.channel, "created_at": n.created_at} for n in rows]


@app.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: int, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if n and n.recipient_id == user.id:
        n.read = True
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- 前端静态文件（生产模式由 run.sh 直接挂载）

import os
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
