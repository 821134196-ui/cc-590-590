"""背调查询发起:严格校验授权状态与获批范围。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..catalog import CHECK_ITEMS
from ..database import get_db
from ..models import Authorization, CheckRequest, User
from ..schemas import CheckIn
from ..security import auth_scope, get_current_user, require_role
from ..services import add_timeline, notify, refresh_auth_status

router = APIRouter(prefix="/api/checks", tags=["checks"])


def check_out(c: CheckRequest) -> dict:
    return {
        "id": c.id,
        "authorization_id": c.authorization_id,
        "item": c.item,
        "item_label": CHECK_ITEMS.get(c.item, {}).get("label", c.item),
        "status": c.status,
        "initiated_by": c.initiated_by,
        "created_at": c.created_at.isoformat(),
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
    }


@router.post("")
def initiate_check(
    body: CheckIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("recruiter")),
):
    auth = db.get(Authorization, body.authorization_id)
    if auth is None:
        raise HTTPException(status_code=404, detail="授权不存在")
    refresh_auth_status(db, auth)  # 惰性到期处理

    if auth.recruiter_id != user.id:
        raise HTTPException(status_code=403, detail="只能基于本人发起的授权发起查询")

    # 授权状态校验:撤回/到期/作废一律禁止发起新查询
    if auth.status == "pending":
        raise HTTPException(status_code=400, detail="候选人尚未同意授权,不能发起查询")
    if auth.status == "revoked":
        raise HTTPException(status_code=403, detail="授权已被候选人撤回,禁止发起新查询")
    if auth.status == "expired":
        raise HTTPException(status_code=403, detail="授权已到期,禁止发起新查询")
    if auth.status == "cancelled":
        raise HTTPException(status_code=403, detail="授权已作废(岗位取消),禁止发起新查询")

    # 范围校验:仅可发起获批范围内的查询
    if body.item not in CHECK_ITEMS:
        raise HTTPException(status_code=400, detail="未知调查项目")
    if body.item not in auth_scope(auth):
        raise HTTPException(
            status_code=403,
            detail=f"调查项目「{CHECK_ITEMS[body.item]['label']}」超出授权范围,禁止发起",
        )

    # 同一项目不可重复发起(已取消的除外)
    existing = (
        db.query(CheckRequest)
        .filter(
            CheckRequest.authorization_id == auth.id,
            CheckRequest.item == body.item,
            CheckRequest.status.in_(["pending", "completed"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="该调查项目已发起过查询")

    check = CheckRequest(
        authorization_id=auth.id, item=body.item, initiated_by=user.id
    )
    db.add(check)
    db.flush()
    add_timeline(
        db,
        "check_initiated",
        f"招聘专员 {user.name} 发起「{CHECK_ITEMS[body.item]['label']}」查询(查询单 #{check.id})",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    agency_user = db.query(User).filter(User.role == "agency").first()
    if agency_user:
        notify(
            db,
            agency_user.id,
            "check_task",
            f"新背调任务 #{check.id}:候选人 {auth.candidate.name},项目「{CHECK_ITEMS[body.item]['label']}」。",
        )
    db.commit()
    db.refresh(check)
    return check_out(check)


@router.get("")
def list_checks(
    authorization_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(CheckRequest)
    if authorization_id is not None:
        q = q.filter(CheckRequest.authorization_id == authorization_id)
    if user.role == "recruiter":
        q = q.join(Authorization, CheckRequest.authorization_id == Authorization.id).filter(
            Authorization.recruiter_id == user.id
        )
    elif user.role == "candidate":
        q = q.join(Authorization, CheckRequest.authorization_id == Authorization.id).filter(
            Authorization.candidate.has(user_id=user.id)
        )
    elif user.role != "compliance":
        raise HTTPException(status_code=403, detail="当前角色无权查看查询单")
    return [check_out(c) for c in q.order_by(CheckRequest.id.desc()).all()]
