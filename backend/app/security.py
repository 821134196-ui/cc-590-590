"""权限判定与业务规则（背调范围、字段分级、回避）。

结果查看分三级，分别授权：
- masked  脱敏结果：隐藏 sensitive 字段。招聘专员（发起人）/合规/候选人本人/回传机构可见
- full    完整材料：sensitive 明文。合规 + 授权书列明的可见人
- raw     原始回执：仅合规；每次查看写访问记录
"""
from datetime import datetime, timezone

from .catalog import CHECK_ITEMS, field_spec


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RuleError(Exception):
    """业务规则违例，携带机器可读 code，由路由转为 HTTP 响应。"""

    def __init__(self, code: str, message: str, http_status: int = 403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------- 授权 / 发起

def consent_is_active(consent) -> bool:
    if consent.status != "granted":
        return False
    if consent.expires_at < _naive_utcnow():
        return False
    return True


def assert_can_create_consent(user):
    if user.role != "recruiter":
        raise RuleError("FORBIDDEN", "只有招聘专员可以拟定背调授权")


def assert_can_initiate_check(user, consent, requested_items: list[str]):
    if user.role != "recruiter":
        raise RuleError("FORBIDDEN", "只有招聘专员可以发起背景调查")
    if consent.recruiter_id != user.id:
        raise RuleError("FORBIDDEN", "该授权不属于当前招聘专员")
    if consent.status == "withdrawn":
        raise RuleError("CONSENT_WITHDRAWN", "候选人已撤回授权，不得发起新查询")
    if consent.status == "position_cancelled":
        raise RuleError("POSITION_CANCELLED", "岗位已取消，不得发起新查询")
    if consent.status != "granted":
        raise RuleError("CONSENT_INVALID", f"授权状态为 {consent.status}，不得发起新查询")
    if consent.expires_at < _naive_utcnow():
        raise RuleError("CONSENT_EXPIRED", "授权已到期，不得发起新查询")
    if not requested_items:
        raise RuleError("EMPTY_ITEMS", "调查项目不能为空", http_status=422)

    approved = set(consent.approved_items)
    unknown = [i for i in requested_items if i not in CHECK_ITEMS]
    if unknown:
        raise RuleError("UNKNOWN_ITEM", f"未知调查项目：{unknown}", http_status=422)
    over = [i for i in requested_items if i not in approved]
    if over:
        labels = [CHECK_ITEMS[i]["label"] for i in over]
        raise RuleError(
            "OUT_OF_SCOPE",
            f"超范围查询：{labels} 不在候选人获批授权范围内",
        )
    if len(set(requested_items)) != len(requested_items):
        raise RuleError("DUP_ITEMS", "调查项目重复", http_status=422)


# ---------------------------------------------------------------- 结果回传

def assert_can_submit_result(user, check):
    if user.role != "agency":
        raise RuleError("FORBIDDEN", "只有合作机构可以回传结果")
    if not user.agency_id or user.agency_id != check.agency_id:
        raise RuleError("AGENCY_MISMATCH", "机构与背调请求指定的机构不一致")


# ---------------------------------------------------------------- 结果查看（三级）

def can_view_masked(user, consent, check) -> bool:
    if user.role == "compliance":
        return True
    if user.id == consent.candidate_id:
        return True
    if user.id == check.requester_id or user.id == consent.recruiter_id:
        return True
    if user.id in (consent.viewer_ids or []):
        return True
    if user.role == "agency" and user.agency_id == check.agency_id:
        return True
    return False


def can_view_full(user, consent) -> bool:
    # 合规始终可见完整材料；授权书列明的可见人可见
    return user.role == "compliance" or user.id in (consent.viewer_ids or [])


def can_view_raw(user, consent) -> bool:
    # 原始回执为最高敏感级，仅合规可见（与完整材料分别授权）
    return user.role == "compliance"


def assert_can_view(user, consent, check, view: str):
    """view: masked / full / raw。返回 (允许等级, 拒绝原因)。"""
    if view == "masked":
        if not can_view_masked(user, consent, check):
            raise RuleError("FORBIDDEN", "无权查看该背调结果")
        return
    if view == "full":
        if not can_view_masked(user, consent, check):
            raise RuleError("FORBIDDEN", "无权查看该背调结果")
        if not can_view_full(user, consent):
            raise RuleError("FULL_MATERIAL_DENIED", "无完整材料权限：敏感字段保持隐藏")
        return
    if view == "raw":
        if not can_view_raw(user, consent):
            raise RuleError("RAW_DENIED", "无原始回执查看权限（仅合规人员）")
        return
    raise RuleError("BAD_VIEW", f"未知查看等级 {view}", http_status=422)


# ---------------------------------------------------------------- 异常 / 更正 / 撤回

def assert_can_raise_anomaly(user):
    if user.role not in ("recruiter", "compliance"):
        raise RuleError("FORBIDDEN", "只有招聘专员或合规人员可以登记异常")


def assert_can_decide_anomaly(user, anomaly):
    if user.role != "compliance":
        raise RuleError("APPROVER_NOT_COMPLIANCE", "只有合规人员可以批准异常结论，招聘专员无权批准")
    if user.id == anomaly.raised_by_id:
        raise RuleError("SELF_APPROVAL", "提交人不能批准自己登记的异常结论（回避原则）")


def assert_can_create_correction(user, consent):
    if user.role != "candidate" or user.id != consent.candidate_id:
        raise RuleError("FORBIDDEN", "只有候选人本人可以对本人结果提出更正")


def assert_can_handle_correction(user):
    if user.role != "compliance":
        raise RuleError("FORBIDDEN", "只有合规人员可以处理更正申请")


def assert_can_withdraw(user, consent):
    if user.role != "candidate" or user.id != consent.candidate_id:
        raise RuleError("FORBIDDEN", "只有候选人本人可以撤回授权")


def assert_can_cancel_position(user, consent):
    if user.role == "compliance":
        return
    if user.role == "recruiter" and user.id == consent.recruiter_id:
        return
    raise RuleError("FORBIDDEN", "只有负责招聘专员或合规人员可以取消岗位")


# ---------------------------------------------------------------- 脱敏 / 覆盖更正

def apply_amendments(payload: dict, amendments) -> dict:
    """把获批更正叠加到机构原始 payload 上（原件不删不改）。"""
    effective = {k: dict(v) if isinstance(v, dict) else v for k, v in (payload or {}).items()}
    for am in amendments:
        item, _, field = am.field_path.partition(".")
        if item in effective and isinstance(effective[item], dict):
            effective[item][field] = am.new_value
    return effective


def render_payload(payload: dict, requested_items: list[str], unmask: bool):
    """按调查范围裁剪并按字段分级脱敏。返回 (渲染后 payload, 被隐藏字段列表)。"""
    masked_fields: list[str] = []
    rendered: dict[str, dict] = {}
    for item_key in requested_items:
        item_data = payload.get(item_key)
        if not isinstance(item_data, dict):
            continue
        spec_item = CHECK_ITEMS.get(item_key, {"fields": {}})
        out = {}
        for field, value in item_data.items():
            spec = spec_item["fields"].get(field)
            level = spec["level"] if spec else "sensitive"
            if level == "sensitive" and not unmask:
                out[field] = "******"
                masked_fields.append(f"{item_key}.{field}")
            else:
                out[field] = value
        rendered[item_key] = out
    return rendered, masked_fields
