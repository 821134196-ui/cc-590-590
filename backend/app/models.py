"""ORM 模型:授权、查询、结果、异常、访问记录、时间线等。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------- 用户与角色 ----------

class User(Base):
    """系统用户。role: recruiter / compliance / candidate / agency"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(128))  # 本地演示环境明文存储
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    candidate_profile: Mapped["Candidate"] = relationship(back_populates="user", uselist=False)


class SessionToken(Base):
    __tablename__ = "session_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    id_number: Mapped[str] = mapped_column(String(32))
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str] = mapped_column(String(128), default="")

    user: Mapped[User] = relationship(back_populates="candidate_profile")


class Position(Base):
    """招聘岗位。status: open / cancelled"""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    department: Mapped[str] = mapped_column(String(64), default="")
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------- 授权与查询 ----------

class Authorization(Base):
    """
    背调授权。候选人同意后激活。
    scope:   JSON 数组,调查项目 key 列表(见 catalog.CHECK_ITEMS)
    viewers: JSON 数组,允许查看(脱敏)结果的用户 id 列表
    status:  pending / active / revoked / expired / cancelled
    """
    __tablename__ = "authorizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"))
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(Text)          # JSON list[str]
    viewers: Mapped[str] = mapped_column(Text)        # JSON list[int]
    purpose: Mapped[str] = mapped_column(String(256), default="招聘录用背景调查")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    candidate: Mapped[Candidate] = relationship()
    position: Mapped[Position] = relationship()
    checks: Mapped[list["CheckRequest"]] = relationship(back_populates="authorization")


class CheckRequest(Base):
    """一次具体调查项目的查询。status: pending / completed / cancelled"""
    __tablename__ = "check_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    authorization_id: Mapped[int] = mapped_column(ForeignKey("authorizations.id"), index=True)
    item: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    initiated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    authorization: Mapped[Authorization] = relationship(back_populates="checks")
    results: Mapped[list["CheckResult"]] = relationship(back_populates="check")


class CheckResult(Base):
    """
    机构回传结果。raw_payload 为原始回执 JSON。
    status: active / duplicate(重复回传,不入正本)
    sealed:  授权撤回或岗位取消后置为 True,按权限封存
    """
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("check_requests.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    conclusion: Mapped[str] = mapped_column(String(16), default="normal")  # normal / abnormal
    raw_payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)
    agency_name: Mapped[str] = mapped_column(String(64), default="本地模拟背调机构")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    check: Mapped[CheckRequest] = relationship(back_populates="results")


# ---------- 异常处理 / 更正 ----------

class AnomalyCase(Base):
    """
    异常结果处理单。招聘专员或合规可提交异常结论建议,
    由合规审批;提交人不得批准自己提交的单据(职责分离)。
    status: open / approved / rejected
    """
    __tablename__ = "anomaly_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("check_results.id"))
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(Text)
    proposed_conclusion: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolution_basis: Mapped[str | None] = mapped_column(Text, nullable=True)  # 处理依据
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    result: Mapped[CheckResult] = relationship()


class CorrectionRequest(Base):
    """候选人更正申请。status: open / resolved / rejected"""
    __tablename__ = "correction_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("check_results.id"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- 审计 ----------

class AccessLog(Base):
    """查看原始回执等敏感操作的访问记录。"""
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    result_id: Mapped[int] = mapped_column(ForeignKey("check_results.id"))
    action: Mapped[str] = mapped_column(String(32), default="view_raw")
    detail: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TimelineEvent(Base):
    """调查与处理时间线:授权、查询、回传、异常、更正、封存等全部事件。"""
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    authorization_id: Mapped[int | None] = mapped_column(ForeignKey("authorizations.id"), nullable=True, index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """本地模拟通知(替代外部通知接口)。"""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
