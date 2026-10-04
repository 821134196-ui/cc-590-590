"""领域服务:时间线、本地模拟通知、结果封存。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import (
    Authorization,
    CheckRequest,
    CheckResult,
    Notification,
    TimelineEvent,
    User,
)


def add_timeline(
    db: Session,
    event_type: str,
    detail: str,
    *,
    authorization_id: int | None = None,
    candidate_id: int | None = None,
    actor_id: int | None = None,
) -> TimelineEvent:
    event = TimelineEvent(
        authorization_id=authorization_id,
        candidate_id=candidate_id,
        actor_id=actor_id,
        event_type=event_type,
        detail=detail,
    )
    db.add(event)
    db.flush()
    return event


def notify(db: Session, user_id: int, type_: str, message: str) -> None:
    """本地模拟通知接口:落库并打印,替代外部短信/邮件服务。"""
    db.add(Notification(user_id=user_id, type=type_, message=message))
    print(f"[mock-notify] -> user#{user_id} [{type_}] {message}")


def seal_authorization_results(
    db: Session, auth: Authorization, *, actor: User | None, reason: str
) -> None:
    """按权限封存授权下全部已有结果,并记录时间线。"""
    results = (
        db.query(CheckResult)
        .join(CheckRequest, CheckResult.check_id == CheckRequest.id)
        .filter(CheckRequest.authorization_id == auth.id)
        .all()
    )
    count = 0
    for r in results:
        if not r.sealed:
            r.sealed = True
            count += 1
    add_timeline(
        db,
        "results_sealed",
        f"{reason};封存结果 {count} 份,此后仅合规人员可依权限调阅,查看原始回执将记录访问日志",
        authorization_id=auth.id,
        candidate_id=auth.candidate_id,
        actor_id=actor.id if actor else None,
    )


def cancel_pending_checks(
    db: Session, auth: Authorization, *, actor: User | None, reason: str
) -> int:
    """取消授权下所有待回传查询。"""
    pending = (
        db.query(CheckRequest)
        .filter(
            CheckRequest.authorization_id == auth.id,
            CheckRequest.status == "pending",
        )
        .all()
    )
    for c in pending:
        c.status = "cancelled"
        add_timeline(
            db,
            "check_cancelled",
            f"查询 #{c.id}({c.item})已取消:{reason}",
            authorization_id=auth.id,
            candidate_id=auth.candidate_id,
            actor_id=actor.id if actor else None,
        )
    return len(pending)


def refresh_auth_status(db: Session, auth: Authorization) -> Authorization:
    """惰性处理到期:激活中的授权超过期限自动置为 expired 并封存。"""
    if auth.status == "active" and auth.expires_at < datetime.utcnow():
        auth.status = "expired"
        cancel_pending_checks(db, auth, actor=None, reason="授权到期")
        seal_authorization_results(db, auth, actor=None, reason="授权到期")
        add_timeline(
            db,
            "authorization_expired",
            f"授权 #{auth.id} 已于 {auth.expires_at.isoformat()} 到期",
            authorization_id=auth.id,
            candidate_id=auth.candidate_id,
        )
        db.commit()
    return auth
