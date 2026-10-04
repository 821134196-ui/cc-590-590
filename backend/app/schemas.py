"""Pydantic 请求/响应模型。"""
from datetime import datetime
from pydantic import BaseModel, Field


# ---------------- 授权

class ConsentCreate(BaseModel):
    candidate_id: int
    recruiter_id: int
    position: str
    approved_items: list[str]
    viewer_ids: list[int]
    valid_days: int = Field(default=30, ge=1, le=3650)
    consent_text: str = ""


class ConsentWithdraw(BaseModel):
    reason: str = ""


class PositionCancel(BaseModel):
    reason: str = ""


# ---------------- 背调请求 / 结果

class CheckCreate(BaseModel):
    consent_id: int
    agency_id: int
    requested_items: list[str]
    reason: str = ""


class ResultSubmit(BaseModel):
    """机构回传结果。第二次对同一请求回传即记为重复回传。"""
    check_code: str
    payload: dict
    raw_receipt: str = ""
    note: str = ""


# ---------------- 异常

class AnomalyCreate(BaseModel):
    check_id: int
    title: str
    conclusion: str
    basis: str = ""
    evidence_ref: str = ""


class AnomalyDecision(BaseModel):
    approve: bool
    decision_note: str = ""
    resolution: str = ""


# ---------------- 更正

class CorrectionCreate(BaseModel):
    check_id: int
    field_path: str          # 形如 employment.salary
    claimed_value: str
    reason: str = ""


class CorrectionDecision(BaseModel):
    approve: bool
    decision_note: str = ""
    corrected_value: str = ""


# ---------------- 通用响应

class Ok(BaseModel):
    ok: bool = True
    message: str = ""
    data: dict | None = None
