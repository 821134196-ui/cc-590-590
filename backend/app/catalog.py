"""调查项目目录与字段分级。

每个调查项目包含若干字段：
- visible：与招聘相关，脱敏结果中可见
- sensitive：与招聘弱相关的敏感字段，脱敏结果默认隐藏，需 VIEW_FULL 权限
- 原始回执（机构原始报文）单独控制，需 VIEW_RAW 权限
"""

CHECK_ITEMS = {
    "identity": {
        "label": "身份核验",
        "fields": {
            "name":          {"label": "姓名", "level": "visible"},
            "id_no":         {"label": "身份证号", "level": "sensitive"},
            "match":         {"label": "人证一致性", "level": "visible"},
        },
    },
    "education": {
        "label": "学历学籍",
        "fields": {
            "school":        {"label": "毕业院校", "level": "visible"},
            "degree":        {"label": "学位", "level": "visible"},
            "graduation":    {"label": "毕业结论", "level": "visible"},
            "student_id":    {"label": "学号", "level": "sensitive"},
        },
    },
    "employment": {
        "label": "工作履历",
        "fields": {
            "employer":      {"label": "曾任单位", "level": "visible"},
            "period":        {"label": "任职时间", "level": "visible"},
            "title":         {"label": "职位", "level": "visible"},
            "leaving_reason": {"label": "离职原因", "level": "sensitive"},
            "salary":        {"label": "过往薪酬", "level": "sensitive"},
        },
    },
    "credit": {
        "label": "信用记录",
        "fields": {
            "summary":       {"label": "信用概要", "level": "visible"},
            "overdue_count": {"label": "逾期次数", "level": "visible"},
            "debt_detail":   {"label": "负债明细", "level": "sensitive"},
            "account_no":    {"label": "金融账号", "level": "sensitive"},
        },
    },
    "criminal": {
    "label": "违法犯罪记录",
        "fields": {
            "result":        {"label": "核查结论", "level": "visible"},
            "record_detail": {"label": "记录详情", "level": "sensitive"},
        },
    },
}

ALL_ITEM_KEYS = list(CHECK_ITEMS.keys())


def field_spec(item_key: str, field: str) -> dict | None:
    item = CHECK_ITEMS.get(item_key)
    if not item:
        return None
    return item["fields"].get(field)
