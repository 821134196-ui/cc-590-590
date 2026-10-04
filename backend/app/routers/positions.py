"""岗位管理:创建、列表、取消(取消后授权作废、待查取消、结果封存)。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Authorization, Position, User
from ..schemas import PositionIn
from ..security import get_current_user, require_role
from ..services import (
    add_timeline,
    cancel_pending_checks,
    notify,
    seal_authorization_results,
)

router = APIRouter(prefix="/api/positions", tags=["positions"])


def position_out(p: Position) -> dict:
    return {
        "id": p.id,
        "title": p.title,
        "department": p.department,
        "recruiter_id": p.recruiter_id,
        "status": p.status,
        "created_at": p.created_at.isoformat(),
        "cancelled_at": p.cancelled_at.isoformat() if p.cancelled_at else None,
    }


@router.post("")
def create_position(
    body: PositionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter")),
):
    p = Position(title=body.title, department=body.department, recruiter_id=user.id)
    db.add(p)
    db.commit()
    db.refresh(p)
    return position_out(p)


@router.get("")
def list_positions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    q = db.query(Position)
    if user.role == "recruiter":
        q = q.filter(Position.recruiter_id == user.id)
    elif user.role not in ("compliance",):
        raise HTTPException(status_code=403, detail="当前角色无权查看岗位")
    return [position_out(p) for p in q.order_by(Position.id.desc()).all()]


@router.post("/{position_id}/cancel")
def cancel_position(
    position_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter")),
):
    p = db.get(Position, position_id)
    if p is None:
        raise HTTPException(status_code=404, detail="岗位不存在")
    if p.recruiter_id != user.id:
        raise HTTPException(status_code=403, detail="只能取消自己负责的岗位")
    if p.status == "cancelled":
        raise HTTPException(status_code=400, detail="岗位已取消")

    p.status = "cancelled"
    p.cancelled_at = datetime.utcnow()

    # 该岗位下所有未完结授权:作废、取消待查、封存结果,全程留时间线
    auths = (
        db.query(Authorization)
        .filter(
            Authorization.position_id == p.id,
            Authorization.status.in_(["pending", "active"]),
        )
        .all()
    )
    for auth in auths:
        auth.status = "cancelled"
        cancel_pending_checks(db, auth, actor=user, reason="岗位取消")
        seal_authorization_results(db, auth, actor=user, reason="岗位取消")
        add_timeline(
            db,
            "position_cancelled",
            f"岗位「{p.title}」已取消,授权 #{auth.id} 随之作废",
            authorization_id=auth.id,
            candidate_id=auth.candidate_id,
            actor_id=user.id,
        )
        notify(
            db,
            auth.candidate.user_id,
            "position_cancelled",
            f"您应聘的岗位「{p.title}」已取消,相关背调授权已作废,已有结果已按权限封存。",
        )
    db.commit()
    return {"ok": True, "cancelled_authorizations": len(auths)}
