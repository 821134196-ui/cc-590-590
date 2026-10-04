"""核心业务规则测试:

1. 超范围查询被阻止
2. 撤回授权后新查询被阻止,已有结果按权限封存
3. 到期授权禁止新查询
4. 结果默认脱敏,敏感字段隐藏
5. 原始回执仅合规可见且留下访问记录
6. 招聘专员不能批准自己提交的异常结论(职责分离)
7. 机构重复回传被隔离并留痕
8. 岗位取消后授权作废、查询取消、结果封存
9. 候选人更正申请流转留痕
"""
from conftest import (
    AGENCY_HEADERS,
    agency_submit,
    consent,
    initiate,
    make_authorization,
    make_position,
)


# ---------- 1. 超范围查询 ----------

def test_out_of_scope_check_blocked(client, recruiter, candidate1):
    pid = make_position(client, recruiter, "范围校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("identity", "education"))
    consent(client, candidate1, auth_id)

    r = initiate(client, recruiter, auth_id, "criminal")  # criminal 不在授权范围
    assert r.status_code == 403
    assert "超出授权范围" in r.json()["detail"]

    # 范围内的项目可以发起
    r = initiate(client, recruiter, auth_id, "identity")
    assert r.status_code == 200


def test_check_before_consent_blocked(client, recruiter):
    pid = make_position(client, recruiter, "未同意岗")
    auth_id = make_authorization(client, recruiter, pid)
    r = initiate(client, recruiter, auth_id, "identity")
    assert r.status_code == 400
    assert "尚未同意" in r.json()["detail"]


# ---------- 2. 撤回授权 ----------

def test_revocation_blocks_new_checks_and_seals_results(client, recruiter, candidate1, compliance):
    pid = make_position(client, recruiter, "撤回校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("identity",))
    consent(client, candidate1, auth_id)

    check_id = initiate(client, recruiter, auth_id, "identity").json()["id"]
    r = agency_submit(client, check_id)
    assert r.status_code == 200 and r.json()["duplicate"] is False
    result_id = r.json()["result_id"]

    # 候选人撤回授权
    r = client.post(f"/api/authorizations/{auth_id}/revoke", headers=candidate1)
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"

    # 撤回后发起新查询被阻止
    r = initiate(client, recruiter, auth_id, "identity")
    assert r.status_code == 403
    assert "撤回" in r.json()["detail"]

    # 已有结果按权限封存:招聘专员不可再见,合规仍可见
    r = client.get(f"/api/results/{result_id}", headers=recruiter)
    assert r.status_code == 403
    r = client.get(f"/api/results/{result_id}", headers=compliance)
    assert r.status_code == 200
    assert r.json()["sealed"] is True

    # 时间线包含撤回与封存事件
    events = client.get(f"/api/authorizations/{auth_id}/timeline", headers=compliance).json()
    types = [e["event_type"] for e in events]
    assert "authorization_revoked" in types
    assert "results_sealed" in types


# ---------- 3. 到期授权 ----------

def test_expired_authorization_blocks_checks(client, recruiter, candidate1):
    pid = make_position(client, recruiter, "到期校验岗")
    # 构造 1 秒后过期的授权,等待其自然过期
    from datetime import datetime, timedelta

    me = client.get("/api/auth/me", headers=recruiter).json()
    r = client.post(
        "/api/authorizations",
        json={
            "candidate_id": 1,
            "position_id": pid,
            "scope": ["identity"],
            "viewer_ids": [me["id"]],
            "expires_at": (datetime.utcnow() + timedelta(seconds=1)).isoformat(),
        },
        headers=recruiter,
    )
    assert r.status_code == 200, r.text
    auth_id = r.json()["id"]
    consent(client, candidate1, auth_id)

    import time

    time.sleep(1.2)
    r = initiate(client, recruiter, auth_id, "identity")
    assert r.status_code == 403
    assert "到期" in r.json()["detail"]


# ---------- 4. 敏感字段默认脱敏 ----------

def test_results_masked_by_default(client, recruiter, candidate1):
    pid = make_position(client, recruiter, "脱敏校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("credit",))
    consent(client, candidate1, auth_id)
    check_id = initiate(client, recruiter, auth_id, "credit").json()["id"]
    result_id = agency_submit(client, check_id).json()["result_id"]

    r = client.get(f"/api/results/{result_id}", headers=recruiter)
    assert r.status_code == 200
    body = r.json()
    assert body["view"] == "masked"
    payload = body["payload"]
    # 敏感字段已脱敏
    assert payload["id_number"] != "110101199501012345"
    assert "****" in payload["phone"]
    assert payload["credit_score"] == "***已脱敏***"
    assert payload["address"].endswith("****")
    # 非敏感字段保留
    assert payload["match"] is True


# ---------- 5. 原始回执权限与访问记录 ----------

def test_raw_receipt_permission_and_access_log(client, recruiter, candidate1, compliance):
    pid = make_position(client, recruiter, "回执校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("identity",))
    consent(client, candidate1, auth_id)
    check_id = initiate(client, recruiter, auth_id, "identity").json()["id"]
    result_id = agency_submit(client, check_id).json()["result_id"]

    # 招聘专员查看原始回执被拒
    r = client.get(f"/api/results/{result_id}?raw=true", headers=recruiter)
    assert r.status_code == 403

    logs_before = client.get("/api/access-logs", headers=compliance).json()
    # 合规查看原始回执成功且完整
    r = client.get(f"/api/results/{result_id}?raw=true", headers=compliance)
    assert r.status_code == 200
    assert r.json()["payload"]["id_number"] == "110101199501012345"

    # 留下访问记录
    logs_after = client.get("/api/access-logs", headers=compliance).json()
    assert len(logs_after) == len(logs_before) + 1
    assert logs_after[0]["result_id"] == result_id
    assert logs_after[0]["action"] == "view_raw"

    # 访问记录接口本身不对招聘专员开放
    r = client.get("/api/access-logs", headers=recruiter)
    assert r.status_code == 403


# ---------- 6. 异常处理:职责分离 ----------

def test_recruiter_cannot_approve_own_anomaly(client, recruiter, candidate1, compliance, compliance2):
    pid = make_position(client, recruiter, "异常校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("employment",))
    consent(client, candidate1, auth_id)
    check_id = initiate(client, recruiter, auth_id, "employment").json()["id"]
    result_id = agency_submit(client, check_id, conclusion="abnormal").json()["result_id"]

    # 招聘专员提交异常结论建议
    r = client.post(
        "/api/anomalies",
        json={
            "result_id": result_id,
            "description": "离职原因与前雇主反馈不一致",
            "proposed_conclusion": "建议降级为待补充材料",
        },
        headers=recruiter,
    )
    assert r.status_code == 200
    case_id = r.json()["id"]

    # 合规审批(非提交人)成功,依据留痕
    r = client.post(
        f"/api/anomalies/{case_id}/resolve",
        json={"decision": "approved", "basis": "依据《背调异常处理规范》第 3 条,补充材料后复核"},
        headers=compliance,
    )
    assert r.status_code == 200
    assert r.json()["resolution_basis"].startswith("依据")

    # 合规自己提交的单据自己不能批准
    r = client.post(
        "/api/anomalies",
        json={"result_id": result_id, "description": "二次复核", "proposed_conclusion": "维持原结论"},
        headers=compliance2,
    )
    case2_id = r.json()["id"]
    r = client.post(
        f"/api/anomalies/{case2_id}/resolve",
        json={"decision": "approved", "basis": "试图自审"},
        headers=compliance2,
    )
    assert r.status_code == 403
    assert "自己提交" in r.json()["detail"]
    # 另一合规人员可以办结
    r = client.post(
        f"/api/anomalies/{case2_id}/resolve",
        json={"decision": "rejected", "basis": "材料不足,驳回"},
        headers=compliance,
    )
    assert r.status_code == 200

    # 时间线包含异常提交与办结
    events = client.get(f"/api/authorizations/{auth_id}/timeline", headers=compliance).json()
    types = [e["event_type"] for e in events]
    assert "anomaly_submitted" in types
    assert "anomaly_resolved" in types


# ---------- 7. 机构重复回传 ----------

def test_duplicate_agency_submission_isolated(client, recruiter, candidate1, compliance):
    pid = make_position(client, recruiter, "重复回传岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("identity",))
    consent(client, candidate1, auth_id)
    check_id = initiate(client, recruiter, auth_id, "identity").json()["id"]

    first = agency_submit(client, check_id).json()
    assert first["duplicate"] is False

    # 重复回传:隔离存档,不覆盖正本
    dup = agency_submit(client, check_id, payload={"match": False, "note": "重复件"})
    assert dup.status_code == 200
    assert dup.json()["duplicate"] is True

    # 正本仍是第一份
    r = client.get(f"/api/results/{first['result_id']}?raw=true", headers=compliance)
    assert r.json()["payload"]["match"] is True

    events = client.get(f"/api/authorizations/{auth_id}/timeline", headers=compliance).json()
    assert "duplicate_result_received" in [e["event_type"] for e in events]


# ---------- 8. 岗位取消 ----------

def test_position_cancellation_cascades(client, recruiter, candidate1, compliance):
    pid = make_position(client, recruiter, "取消校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("identity", "education"))
    consent(client, candidate1, auth_id)
    done_check = initiate(client, recruiter, auth_id, "identity").json()["id"]
    agency_submit(client, done_check)
    initiate(client, recruiter, auth_id, "education")  # 保持 pending

    r = client.post(f"/api/positions/{pid}/cancel", headers=recruiter)
    assert r.status_code == 200

    # 授权作废,新查询被阻止
    r = initiate(client, recruiter, auth_id, "identity")
    assert r.status_code == 403

    # 待查单被取消,机构回传被拒
    checks = client.get(f"/api/checks?authorization_id={auth_id}", headers=compliance).json()
    by_item = {c["item"]: c["status"] for c in checks}
    assert by_item["education"] == "cancelled"
    pending_cancelled_id = next(c["id"] for c in checks if c["item"] == "education")
    r = agency_submit(client, pending_cancelled_id)
    assert r.status_code == 400

    events = client.get(f"/api/authorizations/{auth_id}/timeline", headers=compliance).json()
    types = [e["event_type"] for e in events]
    assert "position_cancelled" in types
    assert "results_sealed" in types


# ---------- 9. 候选人更正申请 ----------

def test_correction_request_flow(client, recruiter, candidate1, compliance):
    pid = make_position(client, recruiter, "更正校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("education",))
    consent(client, candidate1, auth_id)
    check_id = initiate(client, recruiter, auth_id, "education").json()["id"]
    result_id = agency_submit(client, check_id).json()["result_id"]

    r = client.post(
        f"/api/results/{result_id}/corrections",
        json={"content": "毕业年份有误,应为 2017 年"},
        headers=candidate1,
    )
    assert r.status_code == 200
    cr_id = r.json()["id"]

    r = client.post(
        f"/api/corrections/{cr_id}/resolve",
        json={"decision": "resolved", "note": "已与学信网复核并更正"},
        headers=compliance,
    )
    assert r.status_code == 200

    events = client.get(f"/api/authorizations/{auth_id}/timeline", headers=compliance).json()
    types = [e["event_type"] for e in events]
    assert "correction_requested" in types
    assert "correction_resolved" in types


# ---------- 其他权限边界 ----------

def test_other_recruiter_cannot_use_my_authorization(client, recruiter, recruiter2, candidate1):
    pid = make_position(client, recruiter, "归属校验岗")
    auth_id = make_authorization(client, recruiter, pid, scope=("identity",))
    consent(client, candidate1, auth_id)
    r = initiate(client, recruiter2, auth_id, "identity")
    assert r.status_code == 403


def test_unauthenticated_and_agency_token_guard(client):
    assert client.get("/api/authorizations").status_code == 401
    assert client.get("/api/agency/tasks").status_code == 401
    assert client.get("/api/agency/tasks", headers=AGENCY_HEADERS).status_code == 200
