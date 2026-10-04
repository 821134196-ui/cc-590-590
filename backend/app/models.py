"""ORM 模型：用户 / 授权 / 背调请求 / 结果 / 异常 / 更正 / 访问记录 / 时间线 / 通知。"""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    # SQLite 不保留时区信息，统一以 naive UTC 存取与比较
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------- 身份与权限

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    # candidate / recruiter / compliance / agency
    role: Mapped[str] = mapped_column(String(32))
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agencies.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    agency: Mapped["Agency | None"] = relationship(back_populates="users")


class Agency(Base):
    """合作背调机构（外部机构，本地模拟）。"""
    __tablename__ = "agencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    contact: Mapped[str] = mapped_column(String(128), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[list["User"]] = relationship(back_populates="agency")


# ---------------------------------------------------------------- 授权

class Consent(Base):
    """候选人背调授权：调查项目、结果可见人、授权期限。"""
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    position: Mapped[str] = mapped_column(String(128))
    # 获批调查项目（白名单），背调请求只能是其子集
    approved_items: Mapped[list] = mapped_column(JSON, default=list)
    # 授权书中列明“哪些人能看结果”（完整材料）
    viewer_ids: Mapped[list] = mapped_column(JSON, default=list)
    consent_text_snapshot: Mapped[str] = mapped_column(Text, default="")

    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # granted / withdrawn / expired / position_cancelled
    status: Mapped[str] = mapped_column(String(32), default="granted", index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdraw_reason: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str] = mapped_column(Text, default="")

    checks: Mapped[list["CheckRequest"]] = relationship(
        back_populates="consent", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------- 背调请求

class CheckRequest(Base):
    """一次背景调查请求。"""
    __tablename__ = "check_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    consent_id: Mapped[int] = mapped_column(ForeignKey("consents.id"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"))
    requested_items: Mapped[list] = mapped_column(JSON, default=list)

    # pending（机构待回传） / received（已回传） / sealed（已封存）
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seal_reason: Mapped[str] = mapped_column(Text, default="")

    consent: Mapped["Consent"] = relationship(back_populates="checks")
    results: Mapped[list["CheckResult"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )
    anomalies: Mapped[list["Anomaly"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class CheckResult(Base):
    """机构回传的结果（同一请求重复回传会被标记为 duplicate，不覆盖原件）。"""
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("check_requests.id"), index=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"))
    # 结构化字段：{item_key: {field: value}}
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # 原始回执（机构原始报文 / PDF 文本，本地模拟）
    raw_receipt: Mapped[str] = mapped_column(Text, default="")
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)  # 被更正后
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    request: Mapped["CheckRequest"] = relationship(back_populates="results")


class ResultAmendment(Base):
    """候选人更正获批后形成的修正，不删除原件。"""
    __tablename__ = "result_amendments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("check_results.id"), index=True)
    correction_id: Mapped[int] = mapped_column(ForeignKey("correction_requests.id"))
    field_path: Mapped[str] = mapped_column(String(200))
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- 异常处理

class Anomaly(Base):
    """异常结论：招聘/合规提出，合规中另一人批准（禁止自批）。"""
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("check_requests.id"), index=True)
    raised_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    conclusion: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text, default="")          # 认定依据
    evidence_ref: Mapped[str] = mapped_column(String(300), default="")

    # pending / approved / rejected
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text, default="")     # 处理结果
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    request: Mapped["CheckRequest"] = relationship(back_populates="anomalies")


# ---------------------------------------------------------------- 候选人更正

class CorrectionRequest(Base):
    __tablename__ = "correction_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("check_requests.id"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    field_path: Mapped[str] = mapped_column(String(200))
    claimed_value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")
    # pending / approved / rejected
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    handled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    request: Mapped["CheckRequest"] = relationship()


# ---------------------------------------------------------------- 审计：访问记录 / 时间线 / 通知

class AccessLog(Base):
    """敏感材料访问记录（尤其是原始回执）。"""
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("check_requests.id"), index=True)
    # masked_result / full_material / raw_receipt
    target: Mapped[str] = mapped_column(String(32))
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    denied_reason: Mapped[str] = mapped_column(String(64), default="")
    masked_fields: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TimelineEvent(Base):
    """调查与处理时间线（撤回、岗位取消、重复回传、更正等均长期保留）。"""
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("check_requests.id"), nullable=True, index=True)
    consent_id: Mapped[int | None] = mapped_column(ForeignKey("consents.id"), nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Notification(Base):
    """通知（本地模拟，替代短信/邮件/外部 webhook）。"""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(32), default="inapp")  # inapp / email / sms
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
