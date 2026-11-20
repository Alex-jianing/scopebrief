import asyncio
import json
import secrets
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from .api_models import CaseInput
from .harness import answer
from .identity import Account, Conflict
from .store import Store, now, record_audit
from .team import require_admin

MAX_CASES = 60


def _case(row) -> dict:
    return dict(row) | {
        "scope": json.loads(row["scope"]),
        "required_sources": json.loads(row["required_sources"]),
        "active": bool(row["active"]),
    }


class Review:
    def __init__(self, store: Store):
        self.store = store

    def overview(self, actor: Account) -> dict:
        with self.store.connect() as conn:
            conn.execute("BEGIN")
            require_admin(conn, actor)
            stats = dict(
                conn.execute(
                    """
                SELECT COUNT(*) AS runs,
                    COUNT(CASE WHEN r.status IN ('queued','running') THEN 1 END) AS pending,
                    COUNT(CASE WHEN r.status = 'failed' THEN 1 END) AS failed,
                    COALESCE(SUM(json_extract(r.result,'$.usage.total_tokens')),0) AS tokens
                FROM runs r JOIN sessions s ON s.id = r.session_id WHERE s.mode = 'team'
                """,
                ).fetchone()
            )
            feedback = [
                dict(row) | {"scope": json.loads(row["scope"])}
                for row in conn.execute(
                    """
                    SELECT f.run_id,f.note,f.updated_at,r.question,r.scope,a.name AS author
                    FROM feedback f JOIN runs r ON r.id=f.run_id
                    JOIN sessions s ON s.id=r.session_id JOIN accounts a ON a.id=s.account_id
                    WHERE f.rating='review' AND f.resolved_at IS NULL
                    ORDER BY f.updated_at DESC LIMIT 60
                    """
                )
            ]
            cases = [
                _case(row)
                for row in conn.execute("SELECT * FROM review_cases ORDER BY created_at DESC")
            ]
            reports = [
                dict(row)
                for row in conn.execute(
                    """
                SELECT id,created_at,json_extract(body,'$.passed') AS passed,
                    json_extract(body,'$.total') AS total
                FROM review_reports ORDER BY created_at DESC LIMIT 20
                """
                )
            ]
        return {"stats": stats, "feedback": feedback, "cases": cases, "reports": reports}

    def save_case(self, actor: Account, payload: CaseInput, case_id: str | None = None) -> str:
        body = payload
        scope = set(body.project_ids)
        if len(scope) != len(body.project_ids):
            raise ValueError("项目范围包含重复项目。")
        if body.expected_status == "answered" and not (body.required_sources or body.phrase):
            raise ValueError("请为有答案的用例标记证据资料或原文关键词。")
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            project_ids = {row[0] for row in conn.execute("SELECT id FROM projects")}
            if not scope <= project_ids:
                raise ValueError("用例包含不可用项目。")
            sources = set(body.required_sources)
            placeholders = ", ".join("?" for _ in scope)
            known = {
                f"{row['project_id']}/{row['key']}"
                for row in conn.execute(
                    f"SELECT DISTINCT project_id,key FROM documents WHERE project_id IN ({placeholders})",
                    tuple(scope),
                )
            }
            if not sources <= known:
                raise ValueError("所选证据资料需归属用例的项目范围。")
            args = (
                body.title,
                body.question,
                json.dumps(body.project_ids),
                body.expected_status,
                json.dumps(sorted(sources)),
                body.phrase,
            )
            if case_id:
                if not conn.execute(
                    """
                    UPDATE review_cases SET title=?,question=?,scope=?,expected_status=?,
                        required_sources=?,phrase=? WHERE id=?
                    """,
                    (*args, case_id),
                ).rowcount:
                    raise LookupError("未找到该用例。")
            else:
                if conn.execute("SELECT COUNT(*) FROM review_cases").fetchone()[0] >= MAX_CASES:
                    raise Conflict(f"团队回归最多保存 {MAX_CASES} 条用例。")
                if (
                    body.feedback_run_id
                    and not conn.execute(
                        "SELECT 1 FROM feedback WHERE run_id=? AND rating='review' AND resolved_at IS NULL",
                        (body.feedback_run_id,),
                    ).fetchone()
                ):
                    raise LookupError("未找到待复核的反馈。")
                case_id = secrets.token_hex(8)
                try:
                    conn.execute(
                        """
                        INSERT INTO review_cases
                            (id,title,question,scope,expected_status,required_sources,phrase,feedback_run_id,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (case_id, *args, body.feedback_run_id, now()),
                    )
                except sqlite3.IntegrityError as exc:
                    raise Conflict("这条反馈已生成过回归用例。") from exc
                if body.feedback_run_id:
                    conn.execute(
                        "UPDATE feedback SET resolved_at=? WHERE run_id=?",
                        (now(), body.feedback_run_id),
                    )
            record_audit(conn, actor, "case.saved", case_id)
        return case_id

    def toggle_case(self, actor: Account, case_id: str, active: bool) -> None:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            if not conn.execute(
                "UPDATE review_cases SET active=? WHERE id=?", (active, case_id)
            ).rowcount:
                raise LookupError("未找到该用例。")
            record_audit(conn, actor, "case.enabled" if active else "case.disabled", case_id)

    def resolve(self, actor: Account, run_id: str) -> None:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            if not conn.execute(
                "UPDATE feedback SET resolved_at=? WHERE run_id=? AND rating='review'",
                (now(), run_id),
            ).rowcount:
                raise LookupError("未找到该反馈。")
            record_audit(conn, actor, "feedback.resolved", run_id)

    def report(self, actor: Account, report_id: str) -> dict:
        with self.store.connect() as conn:
            require_admin(conn, actor)
            row = conn.execute(
                "SELECT body FROM review_reports WHERE id=?", (report_id,)
            ).fetchone()
        if row is None:
            raise LookupError("未找到该报告。")
        return json.loads(row["body"])

    async def evaluate(self, actor: Account) -> dict:
        # Both documents and cases come from the same read snapshot.
        with TemporaryDirectory(prefix="scopebrief-review-") as tmp:
            path = Path(tmp) / "snapshot.db"
            await asyncio.to_thread(self.store.backup, path)
            snapshot = Store(path)
            with snapshot.connect() as conn:
                require_admin(conn, actor)
                cases = [
                    _case(row)
                    for row in conn.execute(
                        "SELECT * FROM review_cases WHERE active=1 ORDER BY created_at,id"
                    )
                ]
            if not cases:
                raise Conflict("请先添加或启用至少一条回归用例。")
            rows = []
            for case in cases:
                result = await answer(snapshot, actor, case["question"], case["scope"])
                cited = {(item["project_id"], item["key"]) for item in result["citations"]}
                missing = sorted(set(case["required_sources"]) - {"/".join(item) for item in cited})
                quote_ok = not case["phrase"] or any(
                    case["phrase"].casefold() in item["quote"].casefold()
                    for item in result["citations"]
                )
                rows.append(
                    {
                        "id": case["id"],
                        "title": case["title"],
                        "expected_status": case["expected_status"],
                        "status": result["status"],
                        "missing": missing,
                        "phrase_match": quote_ok,
                        "pass": result["status"] == case["expected_status"]
                        and not missing
                        and quote_ok,
                        "versions": list(
                            dict.fromkeys(item["document_id"] for item in result["citations"])
                        ),
                    }
                )
        report = {
            "id": secrets.token_hex(8),
            "created_at": now(),
            "passed": sum(row["pass"] for row in rows),
            "total": len(rows),
            "cases": rows,
        }
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            conn.execute(
                "INSERT INTO review_reports VALUES (?,?,?)",
                (report["id"], report["created_at"], json.dumps(report, ensure_ascii=False)),
            )
            record_audit(conn, actor, "quality.evaluated", report["id"])
        return report
