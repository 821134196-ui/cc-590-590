import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["BAC_DB_PATH"] = _tmp.name

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine, SessionLocal
from app.seed import seed

# 固定身份（见 seed.py）
CAND1, CAND2 = 1, 2
REC_ZHAO, REC_SUN = 3, 4
COMP_ZHOU, COMP_WU = 5, 6
AG_DINGXIN, AG_ANJIAN = 7, 8
AGENCY1, AGENCY2 = 1, 2


@pytest.fixture(scope="session")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed(db)
    db.close()
    with TestClient(app) as c:
        yield c


def h(uid: int) -> dict:
    return {"X-User-Id": str(uid)}


@pytest.fixture
def consent_factory(client):
    def _make(candidate=CAND1, recruiter=REC_ZHAO, items=None, viewers=None, days=30,
              position="高级后端工程师"):
        payload = {
            "candidate_id": candidate, "recruiter_id": recruiter,
            "position": position, "approved_items": items or ["identity", "education", "employment"],
            "viewer_ids": viewers or [COMP_ZHOU], "valid_days": days,
            "consent_text": "本人知悉并授权...",
        }
        r = client.post("/api/consents", json=payload, headers=h(recruiter))
        assert r.status_code == 201, r.text
        return r.json()
    return _make


@pytest.fixture
def check_factory(client, consent_factory):
    def _make(items=None, agency=AGENCY1, **consent_kw):
        consent = consent_factory(items=consent_kw.pop("approved_items", None), **consent_kw)
        body = {"consent_id": consent["id"], "agency_id": agency,
                "requested_items": items or consent["approved_items"], "reason": "录用前背调"}
        r = client.post("/api/checks", json=body, headers=h(consent["recruiter"]["id"]))
        assert r.status_code == 201, r.text
        return consent, r.json()
    return _make


SAMPLE_PAYLOAD = {
    "identity":  {"name": "李明", "id_no": "110101199001011234", "match": "一致"},
    "education": {"school": "示例大学", "degree": "硕士", "graduation": "正常毕业", "student_id": "20120001"},
    "employment": {"employer": "旧公司", "period": "2018-2023", "title": "工程师",
                   "leaving_reason": "个人原因", "salary": "25000"},
}
RAW = "【鼎信背调】原始回执编号 RC-2026-0001；本回执含机构渠道原始报文……"
