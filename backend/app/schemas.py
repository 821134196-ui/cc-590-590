"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    name: str
    role: str


class PositionIn(BaseModel):
    title: str
    department: str = ""


class AuthorizationIn(BaseModel):
    candidate_id: int
    position_id: int
    scope: list[str] = Field(min_length=1)
    viewer_ids: list[int] = Field(min_length=1)
    purpose: str = "招聘录用背景调查"
    expires_at: datetime


class CheckIn(BaseModel):
    authorization_id: int
    item: str


class AgencyResultIn(BaseModel):
    check_id: int
    conclusion: str = Field(pattern="^(normal|abnormal)$")
    payload: dict[str, Any]


class AnomalyIn(BaseModel):
    result_id: int
    description: str
    proposed_conclusion: str


class AnomalyResolveIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    basis: str = Field(min_length=1, description="处理依据,必填留痕")


class CorrectionIn(BaseModel):
    content: str = Field(min_length=1)


class CorrectionResolveIn(BaseModel):
    decision: str = Field(pattern="^(resolved|rejected)$")
    note: str = Field(min_length=1)
