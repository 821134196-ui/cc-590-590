"""测试环境:独立 SQLite 库 + 种子数据。"""
import os
import sys
import tempfile

_TMPDIR = tempfile.mkdtemp(prefix="bgc-test-")
os.environ["BGC_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMPDIR, 'test.db')}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

seed()

AGENCY_HEADERS = {"X-Agency-Token": "local-agency-token"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, username, password="123456") -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def recruiter(client):
    return login(client, "recruiter1")


@pytest.fixture(scope="module")
def recruiter2(client):
    return login(client, "recruiter2")


@pytest.fixture(scope="module")
def compliance(client):
    return login(client, "compliance1")


@pytest.fixture(scope="module")
def compliance2(client):
    return login(client, "compliance2")


@pytest.fixture(scope="module")
def candidate1(client):
    return login(client, "candidate1")


@pytest.fixture(scope="module")
def candidate2(client):
    return login(client, "candidate2")


def make_position(client, recruiter, title="测试岗位"):
    r = client.post("/api/positions", json={"title": title}, headers=recruiter)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def make_authorization(client, recruiter, position_id, candidate_id=1,
                       scope=("identity", "education"), days=30, viewers=(3,)):
    """viewers 默认附加 compliance1(种子 id=3);发起者本人自动加入可见名单。"""
    from datetime import datetime, timedelta

    me = client.get("/api/auth/me", headers=recruiter).json()
    viewer_ids = sorted({me["id"], *viewers})
    r = client.post(
        "/api/authorizations",
        json={
            "candidate_id": candidate_id,
            "position_id": position_id,
            "scope": list(scope),
            "viewer_ids": viewer_ids,
            "expires_at": (datetime.utcnow() + timedelta(days=days)).isoformat(),
        },
        headers=recruiter,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def consent(client, candidate, auth_id):
    r = client.post(f"/api/authorizations/{auth_id}/consent", headers=candidate)
    assert r.status_code == 200, r.text


def initiate(client, recruiter, auth_id, item):
    return client.post(
        "/api/checks",
        json={"authorization_id": auth_id, "item": item},
        headers=recruiter,
    )


def agency_submit(client, check_id, conclusion="normal", payload=None):
    return client.post(
        "/api/agency/results",
        json={
            "check_id": check_id,
            "conclusion": conclusion,
            "payload": payload
            or {
                "match": True,
                "id_number": "110101199501012345",
                "phone": "13800001111",
                "address": "北京市朝阳区某街道 1 号",
                "credit_score": "710",
            },
        },
        headers=AGENCY_HEADERS,
    )
