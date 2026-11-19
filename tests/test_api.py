import json

import pytest
from fastapi.testclient import TestClient

from scopebrief.app import COOKIE, create_app
from scopebrief.settings import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(db=tmp_path / "api.db"))


def run_question(client, text, projects):
    start = client.post("/api/runs", json={"question": text, "project_ids": projects})
    assert start.status_code == 202, start.text
    run_id = start.json()["id"]
    response = client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert frames[-1]["status"] == "done"
    return frames[-1]


def test_run_events_and_isolated_session_history(app):
    with TestClient(app) as client, TestClient(app) as second:
        assert client.get("/api/runs").status_code == 401
        cookie = client.get("/api/session").headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        second.get("/api/session")
        run = run_question(client, "北辰和潮汐可以上线吗？", ["beichen", "tide"])
        assert {"scope", "plan", "retrieve", "verify", "complete"} <= {
            e["stage"] for e in run["events"]
        }
        assert client.get("/api/runs").json()[0]["id"] == run["id"]
        assert second.get("/api/runs").json() == []
        assert second.get("/api/runs/" + run["id"]).status_code == 404
        assert second.get("/api/runs/" + run["id"] + "/events").status_code == 404


def test_document_acl_and_role_change_revokes_cookie(app):
    with TestClient(app) as client:
        client.get("/api/session")
        assert client.get("/api/documents/bridge--release@1").status_code == 404
        assert (
            client.post(
                "/api/runs",
                json={
                    "question": "验收代号",
                    "project_ids": ["bridge"],
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/documents",
                json={
                    "project_id": "beichen",
                    "key": "release",
                    "title": "伪造",
                    "body": "无",
                },
            ).status_code
            == 403
        )
        refused = run_question(client, "铸桥项目的验收代号是什么？", ["beichen", "tide"])
        assert refused["result"]["status"] == "insufficient"
        assert "ORBIT-734" not in json.dumps(refused)
        client.post("/api/session", json={"role": "reviewer"})
        privileged_token = client.cookies.get(COOKIE)
        assert client.get("/api/documents/bridge--release@1").status_code == 200
        privileged = run_question(client, "铸桥项目的验收代号是什么？", ["bridge"])
        assert "ORBIT-734" in privileged["result"]["citations"][0]["quote"]
        client.post("/api/session", json={"role": "member"})
        assert client.get("/api/runs/" + privileged["id"]).status_code == 404
        assert (
            client.get(
                "/api/documents/bridge--release@1",
                headers={
                    "Cookie": f"{COOKIE}={privileged_token}",
                },
            ).status_code
            == 401
        )


def test_publish_updates_retrieval_and_preserves_original_citation(app):
    with TestClient(app) as client:
        client.get("/api/session")
        client.post("/api/session", json={"role": "reviewer"})
        before = run_question(client, "北辰可以上线吗？", ["beichen"])
        previous = before["result"]["citations"][0]
        response = client.post(
            "/api/documents",
            json={
                "project_id": "beichen",
                "key": "release",
                "title": "北辰 · 灰度上线评审",
                "body": "## 放行结论 [decision=hold]\n暂停灰度以验证支付成功率。",
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["revision"] == 3
        current = run_question(client, "北辰可以上线吗？", ["beichen"])
        assert current["result"]["findings"][0]["status"] == "hold"
        assert current["result"]["citations"][0]["revision"] == 3
        archived = client.get("/api/documents/" + previous["document_id"]).json()
        assert archived["revision"] == 2 and not archived["current"]
        matching = archived["body"].splitlines()[previous["start_line"] - 1 : previous["end_line"]]
        assert previous["quote"] in "\n".join(matching)


def test_non_demo_requires_a_role_key(tmp_path):
    app = create_app(
        Settings(
            db=tmp_path / "private.db",
            demo=False,
            member_key="member-key",
            reviewer_key="评审口令",
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/session").json()["role"] is None
        assert (
            client.post("/api/session", json={"role": "reviewer", "key": "member-key"}).status_code
            == 401
        )
        assert (
            client.post("/api/session", json={"role": "reviewer", "key": "评审口令"}).status_code
            == 200
        )
