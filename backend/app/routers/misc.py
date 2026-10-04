"""基础数据:调查项目目录、用户/候选人列表、通知、访问记录。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..catalog import CHECK_ITEMS
from ..database import get_db
from ..models import AccessLog, Candidate, Notification, User
from ..security import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/catalog/items")
def catalog_items():
    return [{"key": k, **v} for k, v in CHECK_ITEMS.items()]


@router.get("/users")
def list_users(
    role: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter", "compliance")),
):
    q = db.query(User).filter(User.role != "agency")
    if role:
        q = q.filter(User.role == role)
    return [{"id": u.id, "name": u.name, "role": u.role} for u in q.order_by(User.id).all()]


@router.get("/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter", "compliance")),
):
    return [
        {"id": c.id, "name": c.name, "email": c.email}
        for c in db.query(Candidate).order_by(Candidate.id).all()
    ]


@router.get("/notifications")
def my_notifications(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": n.id,
            "type": n.type,
            "message": n.message,
            "read": n.read,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]


@router.post("/notifications/read-all")
def read_all_notifications(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.read == False).update({"read": True})
    db.commit()
    return {"ok": True}


@router.get("/access-logs")
def access_logs(
    db: Session = Depends(get_db), user: User = Depends(require_role("compliance"))
):
    """原始回执访问记录(仅合规可见)。"""
    users = {u.id: u.name for u in db.query(User).all()}
    rows = db.query(AccessLog).order_by(AccessLog.id.desc()).limit(200).all()
    return [
        {
            "id": log.id,
            "user": users.get(log.user_id),
            "result_id": log.result_id,
            "action": log.action,
            "detail": log.detail,
            "created_at": log.created_at.isoformat(),
        }
        for log in rows
    ]
