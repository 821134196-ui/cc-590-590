"""关键安全规则测试：
1) 超范围查询被阻止（含撤回/到期/岗位取消）
2) 敏感字段三级权限（脱敏/完整/原始回执）与访问留痕
3) 撤回授权后新查询被阻止、已有结果封存
4) 招聘专员不能批准自己提交的异常结论
5) 重复回传不覆盖、更正保留原件、时间线完整
"""
from conftest import (
    CAND1, CAND2, REC_ZHAO, REC_SUN, COMP_ZHOU, COMP_WU, AG_DINGXIN, AG_ANJIAN,
    AGENCY1, AGENCY2, SAMPLE_PAYLOAD, RAW, h,
)


# ================================================================ 1. 超范围查询

def test_out_of_scope_blocked(client, consent_factory):
    consent = consent_factory(items=["identity", "education"])
    # 申请加入未授权的 criminal / credit
    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": ["identity", "criminal", "credit"],
    }, headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "OUT_OF_SCOPE"


def test_other_recruiter_cannot_initiate(client, consent_factory):
    consent = consent_factory()
    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": consent["approved_items"],
    }, headers=h(REC_SUN))
    assert r.status_code == 403


def test_candidate_cannot_initiate(client, consent_factory):
    consent = consent_factory()
    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": ["identity"],
    }, headers=h(CAND1))
    assert r.status_code == 403


def test_expired_consent_blocks(client, consent_factory):
    consent = consent_factory(days=1)
    # 手工把到期时间改到过去
    from app.database import SessionLocal
    from app.models import Consent
    from datetime import datetime, timezone, timedelta
    db = SessionLocal()
    c = db.get(Consent, consent["id"])
    c.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    db.commit(); db.close()

    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": ["identity"],
    }, headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CONSENT_EXPIRED"


# ================================================================ 2. 字段权限

def _submit(client, check, payload=None, raw=RAW, agency=AG_DINGXIN):
    r = client.post("/api/checks/result", json={
        "check_code": check["code"], "payload": payload or SAMPLE_PAYLOAD, "raw_receipt": raw,
    }, headers=h(agency))
    assert r.status_code == 200, r.text
    return r.json()


def test_masked_hides_sensitive_fields(client, check_factory):
    _, check = check_factory(items=["identity", "education", "employment"])
    _submit(client, check)

    r = client.get(f"/api/checks/{check['id']}/result?view=masked", headers=h(REC_ZHAO))
    assert r.status_code == 200
    data = r.json()
    assert data["payload"]["identity"]["id_no"] == "******"
    assert data["payload"]["employment"]["salary"] == "******"
    assert data["payload"]["identity"]["name"] == "李明"  # 非敏感字段可见
    assert "employment.id_no" not in data["masked_fields"]
    assert "employment.salary" in data["masked_fields"]


def test_recruiter_denied_full_material(client, check_factory):
    _, check = check_factory(items=["identity", "employment"], viewers=[COMP_ZHOU])
    _submit(client, check)
    r = client.get(f"/api/checks/{check['id']}/result?view=full", headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FULL_MATERIAL_DENIED"


def test_named_viewer_sees_full(client, check_factory):
    # viewer 中包含另一位招聘专员孙磊 → 孙磊可看完整材料
    _, check = check_factory(items=["employment"], viewers=[COMP_ZHOU, REC_SUN])
    _submit(client, check)
    r = client.get(f"/api/checks/{check['id']}/result?view=full", headers=h(REC_SUN))
    assert r.status_code == 200
    assert r.json()["payload"]["employment"]["salary"] == "25000"


def test_compliance_full_material(client, check_factory):
    _, check = check_factory(items=["employment"])
    _submit(client, check)
    r = client.get(f"/api/checks/{check['id']}/result?view=full", headers=h(COMP_WU))
    assert r.status_code == 200
    assert r.json()["payload"]["employment"]["salary"] == "25000"


def test_raw_receipt_compliance_only_and_logged(client, check_factory):
    _, check = check_factory()
    _submit(client, check)

    # 招聘专员与候选人均不可看原始回执（即使招聘是授权发起人）
    for uid in (REC_ZHAO, CAND1):
        r = client.get(f"/api/checks/{check['id']}/result?view=raw", headers=h(uid))
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "RAW_DENIED"

    r = client.get(f"/api/checks/{check['id']}/result?view=raw", headers=h(COMP_ZHOU))
    assert r.status_code == 200
    assert "RC-2026-0001" in r.json()["raw_receipt"]

    # 每次查看原始回执都留痕，且拒绝也记录
    logs = client.get("/api/access-logs", params={"check_id": check["id"]}, headers=h(COMP_ZHOU)).json()
    raw_logs = [l for l in logs if l["target"] == "raw_receipt"]
    assert any(l["granted"] and l["user"]["id"] == COMP_ZHOU for l in raw_logs)
    denied = [l for l in logs if not l["granted"]]
    assert {l["denied_reason"] for l in denied} >= {"RAW_DENIED"}


def test_agency_cannot_view_other_agency_check(client, check_factory):
    _, check = check_factory(agency=AGENCY1)
    _submit(client, check)
    r = client.get(f"/api/checks/{check['id']}/result?view=masked", headers=h(AG_ANJIAN))
    assert r.status_code == 403


# ================================================================ 3. 撤回后阻止 + 封存

def test_withdraw_blocks_new_checks_and_seals(client, check_factory):
    consent, check = check_factory(items=["identity", "employment"])
    _submit(client, check)

    r = client.post(f"/api/consents/{consent['id']}/withdraw",
                    json={"reason": "暂不考虑该机会"}, headers=h(CAND1))
    assert r.status_code == 200

    # 撤回后发起新查询被阻止
    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": ["identity"],
    }, headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CONSENT_WITHDRAWN"

    # 已有结果封存：招聘连脱敏版都不能再看
    r = client.get(f"/api/checks/{check['id']}/result?view=masked", headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CHECK_SEALED"

    # 合规仍可审计查看；候选人可看本人脱敏版
    assert client.get(f"/api/checks/{check['id']}/result?view=full",
                      headers=h(COMP_ZHOU)).status_code == 200
    assert client.get(f"/api/checks/{check['id']}/result?view=masked",
                      headers=h(CAND1)).status_code == 200

    # 封存后机构回传被拒绝
    r = client.post("/api/checks/result", json={
        "check_code": check["code"], "payload": SAMPLE_PAYLOAD,
    }, headers=h(AG_DINGXIN))
    assert r.status_code == 403 and r.json()["error"]["code"] == "CHECK_SEALED"


def test_other_candidate_cannot_withdraw(client, consent_factory):
    consent = consent_factory(candidate=CAND1)
    r = client.post(f"/api/consents/{consent['id']}/withdraw",
                    json={"reason": "x"}, headers=h(CAND2))
    assert r.status_code == 403


def test_position_cancelled_blocks_and_seals(client, check_factory):
    consent, check = check_factory()
    _submit(client, check)
    r = client.post(f"/api/consents/{consent['id']}/cancel-position",
                    json={"reason": "HC 冻结"}, headers=h(REC_ZHAO))
    assert r.status_code == 200
    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": ["identity"],
    }, headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "POSITION_CANCELLED"


# ================================================================ 4. 异常处理回避

def test_self_approval_blocked(client, check_factory):
    _, check = check_factory()
    _submit(client, check)

    # 招聘专员赵倩登记异常
    r = client.post("/api/anomalies", json={
        "check_id": check["id"], "title": "学历时间存疑",
        "conclusion": "建议不予录用", "basis": "学信网查询时间与简历不符",
    }, headers=h(REC_ZHAO))
    assert r.status_code == 201
    aid = r.json()["id"]

    # 招聘无权批准
    r = client.post(f"/api/anomalies/{aid}/decision",
                    json={"approve": True, "resolution": "x"}, headers=h(REC_ZHAO))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "APPROVER_NOT_COMPLIANCE"

    # 合规周敏（非提交人）可以批准
    r = client.post(f"/api/anomalies/{aid}/decision",
                    json={"approve": True, "resolution": "维持不予录用",
                          "decision_note": "依据学信网核验记录"}, headers=h(COMP_ZHOU))
    assert r.status_code == 200


def test_compliance_self_approval_blocked(client, check_factory):
    _, check = check_factory()
    _submit(client, check)
    r = client.post("/api/anomalies", json={
        "check_id": check["id"], "title": "履历疑点",
        "conclusion": "需复核", "basis": "证明人无法联系",
    }, headers=h(COMP_WU))
    assert r.status_code == 201
    aid = r.json()["id"]
    # 提交人自己即使是合规也不能批准
    r = client.post(f"/api/anomalies/{aid}/decision",
                    json={"approve": True}, headers=h(COMP_WU))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "SELF_APPROVAL"
    # 另一名合规可以
    r = client.post(f"/api/anomalies/{aid}/decision",
                    json={"approve": False, "decision_note": "证据不足"}, headers=h(COMP_ZHOU))
    assert r.status_code == 200


# ================================================================ 5. 重复回传 / 更正 / 时间线

def test_duplicate_submission_keeps_original(client, check_factory):
    _, check = check_factory(items=["employment"])
    _submit(client, check, SAMPLE_PAYLOAD)

    changed = dict(SAMPLE_PAYLOAD)
    changed["employment"] = {**SAMPLE_PAYLOAD["employment"], "salary": "99999"}
    r = _submit(client, check, changed)
    assert r["duplicate"] is True

    data = client.get(f"/api/checks/{check['id']}/result?view=full",
                      headers=h(COMP_ZHOU)).json()
    # 原结果不被覆盖
    assert data["payload"]["employment"]["salary"] == "25000"
    assert len(data["duplicates"]) == 1

    tl = client.get(f"/api/checks/{check['id']}/timeline", headers=h(REC_ZHAO)).json()
    types = [e["type"] for e in tl]
    assert "result_received" in types and "result_duplicate" in types


def test_wrong_agency_submit_denied(client, check_factory):
    _, check = check_factory(agency=AGENCY1)
    r = client.post("/api/checks/result", json={
        "check_code": check["code"], "payload": SAMPLE_PAYLOAD,
    }, headers=h(AG_ANJIAN))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "AGENCY_MISMATCH"


def test_correction_flow_keeps_timeline(client, check_factory):
    _, check = check_factory(items=["employment"])
    _submit(client, check)

    r = client.post("/api/corrections", json={
        "check_id": check["id"], "field_path": "employment.salary",
        "claimed_value": "30000", "reason": "上月调薪后月薪为3万",
    }, headers=h(CAND1))
    assert r.status_code == 201
    cid = r.json()["id"]

    r = client.post(f"/api/corrections/{cid}/decision",
                    json={"approve": True, "corrected_value": "30000",
                          "decision_note": "已向原单位薪资专员核实"}, headers=h(COMP_ZHOU))
    assert r.status_code == 200

    data = client.get(f"/api/checks/{check['id']}/result?view=full",
                      headers=h(COMP_ZHOU)).json()
    assert data["payload"]["employment"]["salary"] == "30000"
    # 修正记录保留了旧值
    assert data["amendments"][0]["old_value"] == "25000"

    tl = client.get(f"/api/checks/{check['id']}/timeline", headers=h(CAND1)).json()
    assert [e["type"] for e in tl] == [
        "check_initiated", "result_received", "correction_requested", "correction_approved"]


def test_timeline_survives_full_lifecycle(client, consent_factory):
    consent = consent_factory(items=["identity"])
    r = client.post("/api/checks", json={
        "consent_id": consent["id"], "agency_id": AGENCY1,
        "requested_items": ["identity"],
    }, headers=h(REC_ZHAO))
    check = r.json()
    _submit(client, check, {
        "identity": {"name": "李明", "id_no": "110101199001011234", "match": "一致"}})
    client.post(f"/api/consents/{consent['id']}/withdraw",
                json={"reason": "个人原因"}, headers=h(CAND1))

    tl = client.get(f"/api/checks/{check['id']}/timeline", headers=h(COMP_ZHOU)).json()
    types = [e["type"] for e in tl]
    assert types == ["check_initiated", "result_received",
                     "consent_withdrawn", "check_sealed"]
