"""调查项目目录与敏感字段定义。"""
from __future__ import annotations

# 调查项目目录:key -> 展示名、说明、该项目结果中的敏感字段
CHECK_ITEMS: dict[str, dict] = {
    "identity": {
        "label": "身份核验",
        "description": "核对姓名、身份证号一致性",
        "sensitive_fields": ["id_number", "address"],
    },
    "education": {
        "label": "学历核实",
        "description": "核实最高学历及毕业院校",
        "sensitive_fields": ["student_id"],
    },
    "employment": {
        "label": "工作经历核实",
        "description": "核实近两段工作经历与离职原因",
        "sensitive_fields": ["referee_phone"],
    },
    "certification": {
        "label": "专业资格核实",
        "description": "核验岗位相关专业资格证书",
        "sensitive_fields": [],
    },
    "criminal": {
        "label": "犯罪记录查询",
        "description": "查询是否存在犯罪记录(敏感项目)",
        "sensitive_fields": ["case_detail", "case_number"],
    },
    "credit": {
        "label": "个人征信查询",
        "description": "查询个人征信概要(敏感项目)",
        "sensitive_fields": ["credit_score", "loan_detail", "bank_card"],
    },
}

# 所有结果中一律脱敏的通用敏感字段(与招聘决策无关或需最小化暴露)
COMMON_SENSITIVE_FIELDS = {
    "id_number",
    "phone",
    "address",
    "email",
    "bank_card",
    "case_detail",
    "case_number",
    "credit_score",
    "loan_detail",
    "student_id",
    "referee_phone",
}


def all_sensitive_fields() -> set[str]:
    fields = set(COMMON_SENSITIVE_FIELDS)
    for item in CHECK_ITEMS.values():
        fields.update(item["sensitive_fields"])
    return fields
