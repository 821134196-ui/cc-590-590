"""异常结果处理:提交异常结论、合规审批(禁止自审)、保留处理依据。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AnomalyCase,
    Authorization,
    CheckRequest,
    CheckResult,
    User,
)
from ..schemas import AnomalyIn, AnomalyResolveIn
from ..security import get_current_user, require_role
from ..services import add_timeline, notify

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


def case_out(db: Session, c: AnomalyCase) -> dict:
    users = {u.id: u.name for u in db.query(User).all()}
    return {
        "id": c.id,
        "result_id": c.result_id,
        "submitted_by": c.submitted_by,
        "submitted_by_name": users.get(c.submitted_by),
        "description": c.description,
        "proposed_conclusion": c.proposed_conclusion,
        "status": c.status,
        "resolution_basis": c.resolution_basis,
        "resolved_by": c.resolved_by,
        "resolved_by_name": users.get(c.resolved_by) if c.resolved_by else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat(),
    }


@router.post("")
def submit_anomaly(
    body: AnomalyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter", "compliance")),
):
    result = db.get(CheckResult, body.result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="结果不存在")
    check = db.get(CheckRequest, result.check_id)
    auth = db.get(Authorization, check.authorization_id)
    if user.role == "recruiter" and auth.recruiter_id != user.id:
        raise HTTPException(status_code=403, detail="只能对本人负责授权下的结果提交异常结论")

    case = AnomalyCase(
        result_id=result.id,
        submitted_by=user.id,
        description=body.description,
        proposed_conclusion=body.proposed_conclusion,
    )
    db.add(case)
    db.flush()
    add_timeline(
        db,
        "anomaly_submitted",
        f"{user.name} 提交异常结论建议(处理单 #{case.id}):{body.description}",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    for u in db.query(User).filter(User.role == "compliance").all():
        if u.id != user.id:
            notify(db, u.id, "anomaly_open", f"结果 #{result.id} 出现异常处理单 #{case.id},请合规审批。")
    db.commit()
    return case_out(db, case)


@router.get("")
def list_anomalies(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    q = db.query(AnomalyCase).order_by(AnomalyCase.id.desc())
    if user.role == "recruiter":
        q = q.filter(AnomalyCase.submitted_by == user.id)
    elif user.role != "compliance":
        raise HTTPException(status_code=403, detail="当前角色无权查看异常处理单")
    return [case_out(db, c) for c in q.all()]


@router.post("/{case_id}/resolve")
def resolve_anomaly(
    case_id: int,
    body: AnomalyResolveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("compliance")),
):
    case = db.get(AnomalyCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="异常处理单不存在")
    if case.status != "open":
        raise HTTPException(status_code=400, detail="该处理单已办结")
    # 职责分离:任何人不得批准自己提交的异常结论
    if case.submitted_by == user.id:
        raise HTTPException(status_code=403, detail="不能批准自己提交的异常结论,须由其他合规人员处理")

    case.status = body.decision
    case.resolution_basis = body.basis
    case.resolved_by = user.id
    case.resolved_at = datetime.utcnow()

    result = db.get(CheckResult, case.result_id)
    check = db.get(CheckRequest, result.check_id)
    auth = db.get(Authorization, check.authorization_id)
    decision_label = "批准" if body.decision == "approved" else "驳回"
    add_timeline(
        db,
        "anomaly_resolved",
        f"合规 {user.name} {decision_label}异常处理单 #{case.id},依据:{body.basis}",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    notify(db, case.submitted_by, "anomaly_resolved", f"您提交的异常处理单 #{case.id} 已被{decision_label},依据:{body.basis}")
    db.commit()
    return case_out(db, case)
