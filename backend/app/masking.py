"""结果脱敏:默认视图隐藏与招聘无关的敏感字段。"""
from __future__ import annotations

from typing import Any

from .catalog import all_sensitive_fields

SENSITIVE = all_sensitive_fields()


def mask_value(key: str, value: Any) -> Any:
    """按字段类型脱敏,保留可核对的最少信息。"""
    if not isinstance(value, str) or not value:
        return "***"
    n = len(value)
    if key == "id_number":
        return value[:4] + "*" * max(n - 6, 4) + value[-2:] if n > 6 else "******"
    if key in ("phone", "referee_phone"):
        return value[:3] + "****" + value[-2:] if n >= 6 else "1****"
    if key == "bank_card":
        return "**** **** **** " + value[-4:] if n >= 4 else "****"
    if key == "email":
        name, _, domain = value.partition("@")
        return (name[:1] + "***@" + domain) if domain else "***"
    if key == "address":
        return value[:3] + "****" if n > 3 else "****"
    # case_detail / case_number / credit_score / loan_detail / student_id 等
    return "***已脱敏***"


def mask_payload(payload: Any) -> Any:
    """递归脱敏:敏感字段替换为掩码,其余原样返回。"""
    if isinstance(payload, dict):
        return {
            k: (mask_value(k, v) if k in SENSITIVE else mask_payload(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [mask_payload(v) for v in payload]
    return payload
