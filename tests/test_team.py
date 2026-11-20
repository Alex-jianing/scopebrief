import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scopebrief.app import create_app
from scopebrief.http_session import TEAM_COOKIE
from scopebrief.identity import digest
from scopebrief.model import ChatModel
from scopebrief.settings import Settings
from scopebrief.store import Store
from scopebrief.team import Team

PASSWORD = "fixture-test-password!"
QUESTION = "保固条款 GX-782 是什么？"
GUIDE = {
    "project_id": "support",
    "key": "service-guide",
    "title": "客服服务手册",
    "body": "## 保固条款\nGX-782 提供 90 天设备保固，凭设备编号申请。",
}


@pytest.fixture
def deployment(tmp_path):
    settings = Settings(db=tmp_path / "team.db", demo=False)
    app = create_app(settings)
    with TestClient(app) as client:
        store = Store(settings.db)
        activate(
            client,
            Team(store).issue(None, "启动", {}, bootstrap=True)["code"],
            "lead",
            "团队管理员",
        )
        yield client, store


def activate(client, code, username, name):
    response = client.post(
        "/api/auth/activate",
        json={
            "code": code,
            "username": username,
            "name": name,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["account"]


def login(client, username):
    assert (
        client.post(
            "/api/auth/login", json={"username": username, "password": PASSWORD}
        ).status_code
        == 200
    )


def add_project(client, project_id="support", name="客户支持"):
    response = client.post("/api/team/projects", json={"id": project_id, "name": name})
    assert response.status_code == 200, response.text


def new_invite(client, **grants):
    response = client.post("/api/team/invitations", json={"label": "新成员", "grants": grants})
    assert response.status_code == 201, response.text
    return response.json()["code"]


def submit(client, question=QUESTION, project_ids=None):
    response = client.post(
        "/api/runs", json={"question": question, "project_ids": project_ids or ["support"]}
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def wait_run(client, run_id, expected="done"):
    for _ in range(120):
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        row = response.json()
        if row["status"] not in {"running", "queued"}:
            assert row["status"] == expected, row
            return row
        time.sleep(0.03)
    raise AssertionError("run did not reach its terminal state")


def test_member_login_scope_revocation_and_version_history(deployment):
    client, _ = deployment
    assert client.get("/api/session").json()["projects"] == []
    assert client.post("/api/session", json={"role": "reviewer"}).status_code == 404
    add_project(client)
    add_project(client, "restricted", "机密规划")
    assert client.post("/api/documents", json=GUIDE).status_code == 201
    secret = GUIDE | {
        "project_id": "restricted",
        "key": "secret",
        "title": "内部策略",
        "body": "## 保固条款\nGX-782 的内部代号为 NORTHSTAR-519，知识库访问受限。",
    }
    assert client.post("/api/documents", json=secret).status_code == 201
    code = new_invite(client, support="reader")
    client.post("/api/auth/logout", json={})
    member = activate(client, code, "alice", "服务成员")
    response = client.post(
        "/api/auth/activate",
        json={
            "code": code,
            "username": "bob",
            "name": "第二成员",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 403
    assert not client.get("/api/session").json()["projects"][0]["can_edit"]
    assert {d["project_id"] for d in client.get("/api/documents").json()} == {"support"}
    assert client.get("/api/documents/restricted--secret@1").status_code == 404
    assert client.post("/api/documents", json=GUIDE).status_code == 403
    assert (
        client.post(
            "/api/runs",
            json={
                "question": QUESTION,
                "project_ids": ["restricted"],
            },
        ).status_code
        == 404
    )
    old_id = submit(client)
    original = wait_run(client, old_id)
    assert original["result"]["citations"][0]["document_id"] == "support--service-guide@1"
    assert "NORTHSTAR-519" not in str(original)
    assert any("全文索引" in row["detail"] for row in original["events"])
    old_cookie = client.cookies[TEAM_COOKIE]
    assert client.post("/api/auth/logout", json={}).status_code == 200
    assert (
        client.get("/api/runs", headers={"Cookie": f"{TEAM_COOKIE}={old_cookie}"}).status_code
        == 401
    )

    login(client, "lead")
    update = GUIDE | {"body": "## 保固条款\nGX-782 提供 120 天设备保固，凭设备编号申请。"}
    assert client.post("/api/documents", json=update).status_code == 409
    published = client.post("/api/documents", json=update | {"expected_revision": 1})
    assert published.status_code == 201, published.text
    assert client.post("/api/documents", json=update | {"expected_revision": 1}).status_code == 409
    login(client, "alice")
    assert client.get(f"/api/runs/{old_id}").json()["result"]["citations"][0]["revision"] == 1
    assert wait_run(client, submit(client))["result"]["citations"][0]["revision"] == 2
    alice_cookie = client.cookies[TEAM_COOKIE]
    login(client, "lead")
    assert (
        client.post(
            "/api/team/members/" + member["id"], json={"enabled": True, "grants": {}}
        ).status_code
        == 200
    )
    login(client, "alice")
    assert client.get("/api/runs").json() == []
    assert client.get(f"/api/runs/{old_id}").status_code == 404
    assert client.get("/api/documents/support--service-guide@1").status_code == 404
    assert (
        client.get("/api/runs", headers={"Cookie": f"{TEAM_COOKIE}={alice_cookie}"}).status_code
        == 401
    )


def word_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>流程</w:t></w:r></w:p>
            <w:tbl><w:tr><w:tc><w:p><w:r><w:t>项目</w:t></w:r></w:p></w:tc>
                         <w:tc><w:p><w:r><w:t>复核</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
          </w:body>
        </w:document>
        """,
        )
    return buf.getvalue()


def pdf_file():
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    text = DecodedStreamObject()
    text.set_data(b"BT /F1 12 Tf 50 750 Td (Operations SLA BR-120) Tj ET")
    page[NameObject("/Contents")] = text
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("filename", "payload", "match"),
    [
        ("notes.md", b"## doc\ntext", "## doc"),
        ("服务记录.txt", "回单核验".encode("gb18030"), "回单核验"),
        ("流程.docx", word_file(), "项目 | 复核"),
        ("sla.pdf", pdf_file(), "Operations SLA BR-120"),
    ],
)
def test_file_intake_extracts_supported_formats(deployment, filename, payload, match):
    client, _ = deployment
    add_project(client)
    response = client.post(
        "/api/intake/preview",
        params={
            "project_id": "support",
            "filename": filename,
        },
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    assert match in response.json()["body"]
    assert response.json()["source_name"] == filename
    if filename.endswith(".pdf"):
        assert response.json()["body"].startswith("## 第 1 页")


def test_archiving_and_feedback_close_the_evaluation_loop(deployment):
    client, store = deployment
    add_project(client)
    assert client.post("/api/documents", json=GUIDE).status_code == 201
    run_id = submit(client)
    result = wait_run(client, run_id)
    assert result["result"]["status"] == "answered"
    assert (
        client.post(
            f"/api/runs/{run_id}/feedback",
            json={
                "rating": "review",
                "note": "需要持续验证保固期限",
            },
        ).status_code
        == 200
    )
    feedback = client.get("/api/review").json()["feedback"]
    assert feedback[0]["run_id"] == run_id
    case = {
        "title": "核对服务条款",
        "question": QUESTION,
        "project_ids": ["support"],
        "expected_status": "answered",
        "required_sources": ["support/service-guide"],
        "phrase": "90 天",
        "feedback_run_id": run_id,
    }
    assert client.post("/api/review/cases", json=case).status_code == 201
    assert client.get("/api/review").json()["feedback"] == []
    assert client.get(f"/api/runs/{run_id}").json()["feedback"]["resolved_at"]
    first = client.post("/api/review/evaluate", json={})
    assert first.status_code == 200, first.text
    assert first.json()["passed"] == 1

    archive = "/api/documents/support/service-guide/archive"
    assert client.post(archive, json={"archived": True}).status_code == 200
    assert client.get("/api/documents/support--service-guide@1").json()["archived_at"]
    assert wait_run(client, submit(client))["result"]["status"] == "insufficient"
    fail = client.post("/api/review/evaluate", json={}).json()
    assert fail["passed"] == 0
    assert fail["cases"][0]["missing"] == ["support/service-guide"]
    assert client.get("/api/review/reports/" + first.json()["id"]).json()["passed"] == 1
    assert client.post(archive, json={"archived": False}).status_code == 200
    assert wait_run(client, submit(client))["result"]["status"] == "answered"
    store.backup(store.path.with_name("snapshot.db"))
    copy = Store(store.path.with_name("snapshot.db"))
    assert len(copy.documents("reviewer")) == 1
    with pytest.raises(FileExistsError):
        store.backup(copy.path)


def test_queued_work_survives_restart(tmp_path):
    config = Settings(db=tmp_path / "durable.db", demo=False)
    store = Store(config.db)
    with TestClient(create_app(config)) as client:
        activate(
            client,
            Team(store).issue(None, "启动", {}, bootstrap=True)["code"],
            "lead",
            "团队管理员",
        )
        add_project(client)
        client.post("/api/documents", json=GUIDE)
        token = client.cookies[TEAM_COOKIE]
    session = store.session(digest(token), "team")
    assert session
    store.enqueue(session, "persisted-run", QUESTION, ["support"], 64)
    with TestClient(create_app(config)) as client:
        client.cookies.set(TEAM_COOKIE, token)
        assert wait_run(client, "persisted-run")["result"]["status"] == "answered"


def test_cancel_prevents_late_model_result(tmp_path, monkeypatch):
    async def selection(*_args):
        import asyncio

        await asyncio.sleep(100)

    monkeypatch.setattr(ChatModel, "select", selection)
    config = Settings(
        db=tmp_path / "cancel.db",
        demo=False,
        model_base_url="http://127.0.0.1:9999/v1",
        model_name="test",
    )
    with TestClient(create_app(config)) as client:
        activate(
            client,
            Team(Store(config.db)).issue(None, "启动", {}, bootstrap=True)["code"],
            "lead",
            "团队管理员",
        )
        add_project(client)
        client.post("/api/documents", json=GUIDE)
        rid = submit(client)
        for _ in range(100):
            row = client.get(f"/api/runs/{rid}").json()
            if any(e["stage"] == "generate" for e in row["events"]):
                break
            time.sleep(0.02)
        else:
            raise AssertionError("Run did not reach model selection")
        assert client.post(f"/api/runs/{rid}/cancel", json={}).json()["status"] == "cancelled"
        assert wait_run(client, rid, "cancelled")["result"] is None


def test_team_database_rejects_the_demo_mode(tmp_path):
    store = Store(tmp_path / "modes.db")
    store.initialize(seed=False)
    with pytest.raises(RuntimeError, match="separate database"):
        store.initialize()
    assert store.projects("reviewer") == []
