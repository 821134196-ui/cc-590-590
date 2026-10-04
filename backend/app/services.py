"""通知（本地模拟）与时间线记录。"""
from sqlalchemy.orm import Session
from .models import Notification, TimelineEvent


def notify(db: Session, recipient_id: int | None, title: str, content: str = "",
           channel: str = "inapp", commit: bool = False):
    n = Notification(recipient_id=recipient_id, channel=channel, title=title, content=content)
    db.add(n)
    if commit:
        db.commit()
    return n


def log_event(db: Session, event_type: str, *, request_id=None, consent_id=None,
              actor_id=None, detail: dict | None = None, commit: bool = False):
    e = TimelineEvent(
        event_type=event_type, request_id=request_id, consent_id=consent_id,
        actor_id=actor_id, detail=detail or {},
    )
    db.add(e)
    if commit:
        db.commit()
    return e
