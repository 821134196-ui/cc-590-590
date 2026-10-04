"""本地模拟的外部背调机构接口(替代真实机构回调)。

机构通过 X-Agency-Token 调用:
- GET  /api/agency/tasks   待处理调查任务
- POST /api/agency/results 回传结果;重复回传不入正本,记录时间线
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..catalog import CHECK_ITEMS
from ..database import get_db
from ..models import Authorization, CheckRequest, CheckResult
from ..schemas import AgencyResultIn
from ..security import verify_agency_token
from ..services import add_timeline, notify

router = APIRouter(
    prefix="/api/agency",
    tags=["agency"],
    dependencies=[Depends(verify_agency_token)],
)

AGENCY_NAME = "本地模拟背调机构"


@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    tasks = (
        db.query(CheckRequest, Authorization)
        .join(Authorization, CheckRequest.authorization_id == Authorization.id)
        .filter(CheckRequest.status == "pending")
        .order_by(CheckRequest.id.asc())
        .all()
    )
    return [
        {
            "check_id": c.id,
            "item": c.item,
            "item_label": CHECK_ITEMS.get(c.item, {}).get("label", c.item),
            "candidate_name": a.candidate.name if a.candidate else None,
            "position_title": a.position.title if a.position else None,
            "created_at": c.created_at.isoformat(),
        }
        for c, a in tasks
    ]


@router.post("/results")
def submit_result(body: AgencyResultIn, db: Session = Depends(get_db)):
    check = db.get(CheckRequest, body.check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="查询单不存在")
    auth = db.get(Authorization, check.authorization_id)

    if check.status == "cancelled":
        raise HTTPException(status_code=400, detail="查询单已取消,结果不予接收")

    if check.status == "completed":
        # 机构重复回传:保留原结果,重复件单独标记并存入时间线
        dup = CheckResult(
            check_id=check.id,
            version=0,
            conclusion=body.conclusion,
            raw_payload=json.dumps(body.payload, ensure_ascii=False),
            status="duplicate",
            sealed=True,
            agency_name=AGENCY_NAME,
        )
        db.add(dup)
        db.flush()
        add_timeline(
            db,
            "duplicate_result_received",
            f"机构对已完成查询单 #{check.id} 重复回传(重复件 #{dup.id}),已隔离不入正本",
            authorization_id=auth.id,
            candidate_id=auth.candidate_id,
        )
        db.commit()
        return {"ok": True, "duplicate": True, "duplicate_id": dup.id,
                "message": "该查询单已有结果,本次回传按重复件隔离存档"}

    result = CheckResult(
        check_id=check.id,
        version=1,
        conclusion=body.conclusion,
        raw_payload=json.dumps(body.payload, ensure_ascii=False),
        status="active",
        agency_name=AGENCY_NAME,
    )
    db.add(result)
    check.status = "completed"
    check.completed_at = datetime.utcnow()
    db.flush()
    add_timeline(
        db,
        "result_received",
        f"机构回传查询单 #{check.id} 结果(结果 #{result.id},结论:{body.conclusion})",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
    )
    notify(
        db,
        auth.recruiter_id,
        "result_received",
        f"查询单 #{check.id}({CHECK_ITEMS.get(check.item, {}).get('label', check.item)})已有结果回传,请查看(默认脱敏)。",
    )
    db.commit()
    return {"ok": True, "duplicate": False, "result_id": result.id}
