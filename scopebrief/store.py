import json
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .documents import parse_markdown

Role = Literal["member", "reviewer"]
TERMINAL = {"done", "failed"}
FIXTURES = Path(__file__).with_name("fixtures")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
    color TEXT NOT NULL, aliases TEXT NOT NULL, reviewer_only INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
    key TEXT NOT NULL, revision INTEGER NOT NULL, title TEXT NOT NULL,
    body TEXT NOT NULL, published_at TEXT NOT NULL,
    UNIQUE(project_id, key, revision)
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
    heading TEXT NOT NULL, topic TEXT NOT NULL, decision TEXT, content TEXT NOT NULL,
    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, role TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, result TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS runs_owner ON runs(session_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(session_id)
    WHERE status = 'running';
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL, detail TEXT NOT NULL, elapsed_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
"""

WITH_CURRENT = """
    WITH revisions AS (
        SELECT project_id, key, MAX(revision) AS latest
        FROM documents GROUP BY project_id, key
    )
"""
JOIN_CURRENT = "JOIN revisions r ON (r.project_id, r.key) = (d.project_id, d.key)"


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str
    color: str
    aliases: tuple[str, ...]

    def public(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != "aliases"}


@dataclass(frozen=True)
class Evidence:
    id: str
    document_id: str
    project_id: str
    key: str
    revision: int
    title: str
    published_at: str
    current: bool
    heading: str
    topic: str
    decision: str | None
    content: str
    start_line: int
    end_line: int


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
                return
            for project in catalog["projects"]:
                conn.execute(
                    "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        project["id"],
                        project["name"],
                        project["description"],
                        project["color"],
                        json.dumps(project["aliases"]),
                        project["reviewer_only"],
                    ),
                )
            for document in catalog["documents"]:
                for version in document["versions"]:
                    self._publish(
                        conn,
                        document["project_id"],
                        document["key"],
                        version["title"],
                        version["body"],
                        version["date"],
                    )

    def projects(self, role: Role) -> list[Project]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE reviewer_only = 0 OR ? ORDER BY rowid",
                (role == "reviewer",),
            ).fetchall()
        return [
            Project(
                row["id"],
                row["name"],
                row["description"],
                row["color"],
                tuple(json.loads(row["aliases"])),
            )
            for row in rows
        ]

    def documents(self, role: Role, document_id: str | None = None) -> list[dict]:
        select = (
            "d.*, "
            if document_id is not None
            else ("d.id, d.project_id, d.key, d.revision, d.title, d.published_at, ")
        )
        with self.connect() as conn:
            rows = conn.execute(
                WITH_CURRENT
                + f"""
                SELECT {select} d.revision = r.latest AS current FROM documents d
                {JOIN_CURRENT}
                JOIN projects p ON d.project_id = p.id
                WHERE (p.reviewer_only = 0 OR ?) AND (? IS NULL OR d.id = ?)
                ORDER BY d.project_id, d.key, d.revision DESC
                """,
                (role == "reviewer", document_id, document_id),
            ).fetchall()
        return [dict(row) | {"current": bool(row["current"])} for row in rows]

    def evidence(self, role: Role, scope: list[str], current_only: bool) -> list[Evidence]:
        if not scope:
            return []
        placeholders = ", ".join("?" for _ in scope)
        with self.connect() as conn:
            rows = conn.execute(
                WITH_CURRENT
                + f"""
                SELECT c.*, d.project_id, d.key, d.revision, d.title, d.published_at,
                    d.revision = r.latest AS current
                FROM chunks c JOIN documents d ON c.document_id = d.id
                {JOIN_CURRENT}
                JOIN projects p ON d.project_id = p.id
                WHERE (p.reviewer_only = 0 OR ?) AND p.id IN ({placeholders})
                    AND (? = 0 OR d.revision = r.latest)
                ORDER BY d.published_at DESC, c.start_line, c.id
                """,
                (role == "reviewer", *scope, current_only),
            ).fetchall()
        return [Evidence(**(dict(row) | {"current": bool(row["current"])})) for row in rows]

    def publish(self, project_id: str, key: str, title: str, body: str) -> str:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._publish(conn, project_id, key, title, body, now())

    @staticmethod
    def _publish(conn, project_id: str, key: str, title: str, body: str, date: str) -> str:
        sections = parse_markdown(body)
        revision = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM documents WHERE project_id = ? AND key = ?",
            (project_id, key),
        ).fetchone()[0]
        version_id = f"{project_id}--{key}@{revision}"
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
            (version_id, project_id, key, revision, title, body, date),
        )
        conn.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    f"{version_id}:{i}",
                    version_id,
                    row.heading,
                    row.topic,
                    row.decision,
                    row.content,
                    row.start_line,
                    row.end_line,
                )
                for i, row in enumerate(sections, 1)
            ],
        )
        return version_id

    def get_role(self, session_id: str) -> Role | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT role FROM sessions WHERE id = ? AND expires_at > ?",
                (session_id, int(time.time())),
            ).fetchone()
        return row["role"] if row else None

    def add_session(self, session_id: str, role: Role, ttl: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)", (session_id, role, int(time.time()) + ttl)
            )

    def remove_session(self, session_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def start_run(self, session_id: str, run_id: str, question: str, scope: list[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, 'running', ?, NULL, NULL)",
                (run_id, session_id, question, json.dumps(scope), now()),
            )

    def add_event(self, run_id: str, stage: str, detail: str, elapsed_ms: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events (run_id, stage, detail, elapsed_ms) VALUES (?, ?, ?, ?)",
                (run_id, stage, detail, elapsed_ms),
            )

    def finish_run(self, run_id: str, result: dict | None, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, result = ?, error = ? WHERE id = ?",
                (
                    "done" if result is not None else "failed",
                    json.dumps(result, ensure_ascii=False) if result else None,
                    error,
                    run_id,
                ),
            )

    def recover_runs(self) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = 'failed', error = ? WHERE status = 'running'",
                ("服务已重启，请重新发起提问。",),
            )

    def runs(self, session_id: str) -> list[dict]:
        with self.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    """
                SELECT id, question, status, created_at FROM runs WHERE session_id = ?
                ORDER BY created_at DESC LIMIT 24
                """,
                    (session_id,),
                )
            ]

    def run(self, session_id: str, run_id: str) -> dict | None:
        with self.connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT * FROM runs WHERE session_id = ? AND id = ?",
                (session_id, run_id),
            ).fetchone()
            if row is None:
                return None
            events = conn.execute(
                "SELECT id, stage, detail, elapsed_ms FROM events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return {
            "id": row["id"],
            "question": row["question"],
            "status": row["status"],
            "created_at": row["created_at"],
            "scope": json.loads(row["scope"]),
            "result": json.loads(row["result"]) if row["result"] is not None else None,
            "error": row["error"],
            "events": [dict(event) for event in events],
        }
