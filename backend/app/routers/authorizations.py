"""授权:发起、候选人同意/撤回、授权页(范围/可见人/到期)、时间线。"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..catalog import CHECK_ITEMS
from ..database import get_db
from ..models import Authorization, Candidate, Position, TimelineEvent, User
from ..schemas import AuthorizationIn
from ..security import (
    auth_scope,
    auth_viewer_ids,
    get_current_user,
    require_role,
)
from ..services import (
    add_timeline,
    cancel_pending_checks,
    notify,
    refresh_auth_status,
    seal_authorization_results,
)

router = APIRouter(prefix="/api/authorizations", tags=["authorizations"])

STATUS_LABELS = {
    "pending": "待候选人同意",
    "active": "授权有效",
    "revoked": "已撤回",
    "expired": "已到期",
    "cancelled": "已作废",
}


def auth_out(db: Session, auth: Authorization) -> dict:
    viewers = (
        db.query(User).filter(User.id.in_(auth_viewer_ids(auth))).all()
        if auth_viewer_ids(auth)
        else []
    )
    return {
        "id": auth.id,
        "candidate_id": auth.candidate_id,
        "candidate_name": auth.candidate.name if auth.candidate else None,
        "position_id": auth.position_id,
        "position_title": auth.position.title if auth.position else None,
        "recruiter_id": auth.recruiter_id,
        "purpose": auth.purpose,
        "scope": [
            {"key": k, "label": CHECK_ITEMS[k]["label"], "description": CHECK_ITEMS[k]["description"]}
            for k in auth_scope(auth)
            if k in CHECK_ITEMS
        ],
        "viewers": [{"id": v.id, "name": v.name, "role": v.role} for v in viewers],
        "status": auth.status,
        "status_label": STATUS_LABELS.get(auth.status, auth.status),
        "expires_at": auth.expires_at.isoformat(),
        "created_at": auth.created_at.isoformat(),
        "consented_at": auth.consented_at.isoformat() if auth.consented_at else None,
        "revoked_at": auth.revoked_at.isoformat() if auth.revoked_at else None,
    }


def get_auth_or_404(db: Session, auth_id: int) -> Authorization:
    auth = db.get(Authorization, auth_id)
    if auth is None:
        raise HTTPException(status_code=404, detail="授权不存在")
    return refresh_auth_status(db, auth)


@router.post("")
def create_authorization(
    body: AuthorizationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter")),
):
    position = db.get(Position, body.position_id)
    if position is None or position.recruiter_id != user.id:
        raise HTTPException(status_code=404, detail="岗位不存在或不属于当前招聘专员")
    if position.status != "open":
        raise HTTPException(status_code=400, detail="岗位已取消,无法发起授权")
    candidate = db.get(Candidate, body.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选人不存在")
    unknown = [k for k in body.scope if k not in CHECK_ITEMS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知调查项目: {unknown}")
    if body.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="到期时间必须晚于当前时间")
    viewers = db.query(User).filter(User.id.in_(body.viewer_ids)).all()
    if len(viewers) != len(set(body.viewer_ids)):
        raise HTTPException(status_code=400, detail="结果可见人名单中存在无效用户")

    auth = Authorization(
        candidate_id=candidate.id,
        position_id=position.id,
        recruiter_id=user.id,
        scope=json.dumps(body.scope),
        viewers=json.dumps(sorted(set(body.viewer_ids))),
        purpose=body.purpose,
        expires_at=body.expires_at,
    )
    db.add(auth)
    db.flush()
    add_timeline(
        db,
        "authorization_created",
        f"招聘专员 {user.name} 发起背调授权,调查项目 {len(body.scope)} 项,"
        f"到期时间 {body.expires_at.isoformat()},等待候选人同意",
        authorization_id=auth.id,
        candidate_id=candidate.id,
        actor_id=user.id,
    )
    notify(
        db,
        candidate.user_id,
        "authorization_pending",
        f"{user.name} 为您发起岗位「{position.title}」的背调授权,请查看调查项目、可见人员与授权期限并确认。",
    )
    db.commit()
    db.refresh(auth)
    return auth_out(db, auth)


@router.get("")
def list_authorizations(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    q = db.query(Authorization)
    if user.role == "recruiter":
        q = q.filter(Authorization.recruiter_id == user.id)
    elif user.role == "candidate":
        q = q.join(Candidate, Authorization.candidate_id == Candidate.id).filter(
            Candidate.user_id == user.id
        )
    elif user.role != "compliance":
        raise HTTPException(status_code=403, detail="当前角色无权查看授权")
    auths = [refresh_auth_status(db, a) for a in q.order_by(Authorization.id.desc()).all()]
    return [auth_out(db, a) for a in auths]


@router.get("/{auth_id}")
def get_authorization(
    auth_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    auth = get_auth_or_404(db, auth_id)
    if user.role == "candidate" and auth.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看他人授权")
    if user.role == "recruiter" and auth.recruiter_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看他人发起的授权")
    return auth_out(db, auth)


@router.post("/{auth_id}/consent")
def consent(
    auth_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate")),
):
    auth = get_auth_or_404(db, auth_id)
    if auth.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能操作本人的授权")
    if auth.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态({auth.status})不可同意")
    auth.status = "active"
    auth.consented_at = datetime.utcnow()
    add_timeline(
        db,
        "candidate_consented",
        f"候选人 {auth.candidate.name} 同意授权,授权生效",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    notify(db, auth.recruiter_id, "authorization_active", f"候选人 {auth.candidate.name} 已同意授权 #{auth.id},可在获批范围内发起查询。")
    db.commit()
    return auth_out(db, auth)


@router.post("/{auth_id}/revoke")
def revoke(
    auth_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate")),
):
    auth = get_auth_or_404(db, auth_id)
    if auth.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能操作本人的授权")
    if auth.status not in ("pending", "active"):
        raise HTTPException(status_code=400, detail=f"当前状态({auth.status})不可撤回")

    auth.status = "revoked"
    auth.revoked_at = datetime.utcnow()
    add_timeline(
        db,
        "authorization_revoked",
        f"候选人 {auth.candidate.name} 撤回授权,禁止发起任何新查询",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    cancel_pending_checks(db, auth, actor=user, reason="候选人撤回授权")
    seal_authorization_results(db, auth, actor=user, reason="候选人撤回授权")
    notify(db, auth.recruiter_id, "authorization_revoked", f"候选人 {auth.candidate.name} 已撤回授权 #{auth.id},请勿再发起查询。")
    db.commit()
    return auth_out(db, auth)


@router.get("/{auth_id}/timeline")
def timeline(
    auth_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    auth = get_auth_or_404(db, auth_id)
    allowed = user.role == "compliance" or (
        user.role == "recruiter" and auth.recruiter_id == user.id
    ) or (user.role == "candidate" and auth.candidate.user_id == user.id)
    if not allowed:
        raise HTTPException(status_code=403, detail="无权查看该授权时间线")
    events = (
        db.query(TimelineEvent)
        .filter(TimelineEvent.authorization_id == auth.id)
        .order_by(TimelineEvent.id.asc())
        .all()
    )
    actors = {u.id: u.name for u in db.query(User).all()}
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "detail": e.detail,
            "actor": actors.get(e.actor_id, "系统"),
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
