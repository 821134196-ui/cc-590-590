"""结果查看:默认脱敏;原始回执单独鉴权并记录访问日志。候选人可发起更正。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..catalog import CHECK_ITEMS
from ..database import get_db
from ..masking import mask_payload
from ..models import (
    Authorization,
    CheckRequest,
    CheckResult,
    CorrectionRequest,
    User,
)
from ..schemas import CorrectionIn
from ..security import can_view_masked, can_view_raw, get_current_user, require_role
from ..services import add_timeline, notify

router = APIRouter(prefix="/api/results", tags=["results"])


def result_out(r: CheckResult, check: CheckRequest, *, raw: bool) -> dict:
    payload = json.loads(r.raw_payload)
    return {
        "id": r.id,
        "check_id": r.check_id,
        "authorization_id": check.authorization_id,
        "item": check.item,
        "item_label": CHECK_ITEMS.get(check.item, {}).get("label", check.item),
        "conclusion": r.conclusion,
        "status": r.status,
        "sealed": r.sealed,
        "agency_name": r.agency_name,
        "view": "raw" if raw else "masked",
        "payload": payload if raw else mask_payload(payload),
        "created_at": r.created_at.isoformat(),
    }


def load_visible_result(db: Session, result_id: int, user: User) -> tuple[CheckResult, CheckRequest, Authorization]:
    r = db.get(CheckResult, result_id)
    if r is None:
        raise HTTPException(status_code=404, detail="结果不存在")
    check = db.get(CheckRequest, r.check_id)
    auth = db.get(Authorization, check.authorization_id)
    return r, check, auth


@router.get("")
def list_results(
    authorization_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """脱敏结果列表(默认视图,敏感字段已隐藏)。"""
    q = (
        db.query(CheckResult, CheckRequest, Authorization)
        .join(CheckRequest, CheckResult.check_id == CheckRequest.id)
        .join(Authorization, CheckRequest.authorization_id == Authorization.id)
        .filter(CheckResult.status == "active")
        .order_by(CheckResult.id.desc())
    )
    if authorization_id is not None:
        q = q.filter(Authorization.id == authorization_id)
    out = []
    for r, check, auth in q.all():
        if can_view_masked(user, auth):
            out.append(result_out(r, check, raw=False))
    return out


@router.get("/{result_id}")
def get_result(
    result_id: int,
    raw: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r, check, auth = load_visible_result(db, result_id, user)
    if raw:
        # 原始回执:独立权限(仅合规),且每次访问写入访问记录
        if not can_view_raw(user, auth):
            raise HTTPException(
                status_code=403,
                detail="无原始回执查看权限(完整材料与脱敏结果分别授权)",
            )
        from ..models import AccessLog

        db.add(
            AccessLog(
                user_id=user.id,
                result_id=r.id,
                action="view_raw",
                detail=f"查看结果 #{r.id} 原始回执",
            )
        )
        add_timeline(
            db,
            "raw_receipt_viewed",
            f"{user.name}({user.role})查看了结果 #{r.id} 的原始回执,已记录访问日志",
            authorization_id=auth.id,
            candidate_id=auth.candidate_id,
            actor_id=user.id,
        )
        db.commit()
        return result_out(r, check, raw=True)

    if not can_view_masked(user, auth):
        raise HTTPException(status_code=403, detail="无脱敏结果查看权限")
    return result_out(r, check, raw=False)


@router.post("/{result_id}/corrections")
def request_correction(
    result_id: int,
    body: CorrectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("candidate")),
):
    """候选人对涉及本人的结果提出更正申请。"""
    r, check, auth = load_visible_result(db, result_id, user)
    if auth.candidate.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能对本人的结果申请更正")
    cr = CorrectionRequest(
        result_id=r.id, candidate_id=auth.candidate_id, content=body.content
    )
    db.add(cr)
    db.flush()
    add_timeline(
        db,
        "correction_requested",
        f"候选人就结果 #{r.id} 提出更正申请(申请单 #{cr.id}):{body.content}",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=user.id,
    )
    for u in db.query(User).filter(User.role == "compliance").all():
        notify(db, u.id, "correction_requested", f"候选人 {auth.candidate.name} 对结果 #{r.id} 提出更正申请,请处理。")
    db.commit()
    return {"id": cr.id, "status": cr.status}
