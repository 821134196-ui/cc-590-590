"""更正申请处理(合规)与查询。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Authorization,
    CheckRequest,
    CheckResult,
    CorrectionRequest,
    User,
)
from ..schemas import CorrectionResolveIn
from ..security import get_current_user, require_role
from ..services import add_timeline, notify

router = APIRouter(prefix="/api/corrections", tags=["corrections"])


def cr_out(db: Session, cr: CorrectionRequest) -> dict:
    users = {u.id: u.name for u in db.query(User).all()}
    return {
        "id": cr.id,
        "result_id": cr.result_id,
        "candidate_id": cr.candidate_id,
        "content": cr.content,
        "status": cr.status,
        "resolution_note": cr.resolution_note,
        "resolved_by_name": users.get(cr.resolved_by) if cr.resolved_by else None,
        "resolved_at": cr.resolved_at.isoformat() if cr.resolved_at else None,
        "created_at": cr.created_at.isoformat(),
    }


@router.get("")
def list_corrections(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    q = db.query(CorrectionRequest).order_by(CorrectionRequest.id.desc())
    if user.role == "candidate":
        q = q.filter(CorrectionRequest.candidate.has(user_id=user.id))
    elif user.role != "compliance":
        raise HTTPException(status_code=403, detail="当前角色无权查看更正申请")
    return [cr_out(db, c) for c in q.all()]


@router.post("/{cr_id}/resolve")
def resolve_correction(
    cr_id: int,
    body: CorrectionResolveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("compliance")),
):
    cr = db.get(CorrectionRequest, cr_id)
    if cr is None:
        raise HTTPException(status_code=404, detail="更正申请不存在")
    if cr.status != "open":
        raise HTTPException(status_code=400, detail="该申请已办结")

    cr.status = body.decision
    cr.resolution_note = body.note
    cr.resolved_by = user.id
    cr.resolved_at = datetime.utcnow()

    result = db.get(CheckResult, cr.result_id)
    check = db.get(CheckRequest, result.check_id)
    auth = db.get(Authorization, check.authorization_id)
    label = "已更正" if body.decision == "resolved" else "已驳回"
    add_timeline(
        db,
        "correction_resolved",
        f"合规 {user.name} 办结更正申请 #{cr.id}({label}),说明:{body.note}",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    notify(db, auth.candidate.user_id, "correction_resolved", f"您的更正申请 #{cr.id} {label},说明:{body.note}")
    db.commit()
    return cr_out(db, cr)
