import json
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .documents import parse_markdown
from .identity import Access, Account, Conflict, Denied, Mode, QueueFull, Session
from .lexicon import tokens
from .team_schema import PROJECT_ACCESS, TEAM_SCHEMA

TERMINAL = {"done", "failed", "cancelled"}
FIXTURES = Path(__file__).with_name("fixtures")
SCHEMA_VERSION = 3

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
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_index USING fts5(terms);
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
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS run_queue ON runs(status, created_at);
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


def project_access(access: Access, write: bool = False) -> tuple[str, tuple]:
    if isinstance(access, Account):
        return PROJECT_ACCESS, (access.id, write)
    if write:
        return "?", (access == "reviewer",)
    return "(p.reviewer_only = 0 OR ?)", (access == "reviewer",)


def record_audit(conn, actor: Account | None, action: str, target: str) -> None:
    conn.execute(
        "INSERT INTO audit (at, actor_id, action, target) VALUES (?, ?, ?, ?)",
        (now(), actor.id if actor else None, action, target),
    )


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

    def initialize(self, *, seed: bool = True) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            previous = conn.execute("PRAGMA user_version").fetchone()[0]
            if previous > SCHEMA_VERSION:
                raise RuntimeError("This database requires a newer version of ScopeBrief")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA + TEAM_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            expected = "sandbox" if seed else "team"
            existing = conn.execute(
                "SELECT value FROM workspace_settings WHERE key = 'data_mode'"
            ).fetchone()
            populated = conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
            if (existing and existing["value"] != expected) or (
                not existing and populated and not seed
            ):
                raise RuntimeError("Use a separate database for team and demo workspaces")
            conn.execute(
                "INSERT OR IGNORE INTO workspace_settings VALUES ('data_mode', ?)", (expected,)
            )

            if previous < SCHEMA_VERSION:
                self._migrate_columns(conn)
                self._backfill_search(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            if not seed or populated:
                return
            catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
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

    @staticmethod
    def _migrate_columns(conn) -> None:
        for table, additions in {
            "sessions": (
                ("mode", "TEXT NOT NULL DEFAULT 'demo'"),
                ("account_id", "TEXT REFERENCES accounts(id)"),
            ),
            "documents": (
                ("source_name", "TEXT NOT NULL DEFAULT ''"),
                ("change_note", "TEXT NOT NULL DEFAULT ''"),
            ),
        }.items():
            fields = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for key, declaration in additions:
                if key not in fields:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {key} {declaration}")
        conn.execute("CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account_id)")
        conn.execute("DROP INDEX IF EXISTS one_active_run")
        conn.execute(
            "CREATE UNIQUE INDEX one_active_run ON runs(session_id) "
            "WHERE status IN ('queued', 'running')"
        )

    @staticmethod
    def _backfill_search(conn) -> None:
        rows = conn.execute(
            """
            SELECT c.rowid,c.heading,c.content,d.title FROM chunks c JOIN documents d ON c.document_id=d.id
            WHERE NOT EXISTS (SELECT 1 FROM chunk_index f WHERE f.rowid=c.rowid)
            """
        )
        conn.executemany(
            "INSERT INTO chunk_index (rowid,terms) VALUES (?,?)",
            [(row[0], " ".join(tokens(" ".join(row[1:])))) for row in rows],
        )

    def projects(self, access: Access, *, writable: bool = False) -> list[Project]:
        allowed, args = project_access(access, writable)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT p.* FROM projects p WHERE {allowed} ORDER BY p.rowid",
                args,
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

    def documents(self, access: Access, document_id: str | None = None) -> list[dict]:
        allowed, args = project_access(access)
        select = (
            "d.*, "
            if document_id is not None
            else (
                "d.id, d.project_id, d.key, d.revision, d.title, d.published_at, "
                "d.source_name, d.change_note, "
            )
        )
        with self.connect() as conn:
            rows = conn.execute(
                WITH_CURRENT
                + f"""
                SELECT {select} d.revision = r.latest AS current, life.archived_at
                FROM documents d
                {JOIN_CURRENT}
                JOIN projects p ON d.project_id = p.id
                LEFT JOIN document_lifecycle life ON (life.project_id, life.key) = (d.project_id, d.key)
                WHERE {allowed} AND (? IS NULL OR d.id = ?)
                ORDER BY d.project_id, d.key, d.revision DESC
                """,
                (*args, document_id, document_id),
            ).fetchall()
        return [dict(row) | {"current": bool(row["current"])} for row in rows]

    def evidence(
        self,
        access: Access,
        scope: list[str],
        current_only: bool,
        *,
        match_terms: set[str] | None = None,
        topics: list[str] | None = None,
    ) -> list[Evidence]:
        if not scope:
            return []
        placeholders = ", ".join("?" for _ in scope)
        allowed, args = project_access(access)
        filters, parameters = [], []
        if match_terms:
            filters.append("""
                ref IN (
                    SELECT ref FROM (
                        SELECT m.ref, ROW_NUMBER() OVER (
                            PARTITION BY m.project_id ORDER BY f.rank, m.ref
                        ) AS position
                        FROM chunk_index f JOIN permitted m ON m.ref=f.rowid
                        WHERE chunk_index MATCH ?
                    ) WHERE position <= 48
                )
            """)
            parameters.append(" OR ".join(f'"{term}"' for term in sorted(match_terms)[:128]))
        if topics:
            filters.append("topic IN (" + ", ".join("?" for _ in topics) + ")")
            parameters.extend(topics)
        shortlist = " OR ".join(filters) or ("0" if match_terms is not None else "1")
        with self.connect() as conn:
            rows = conn.execute(
                WITH_CURRENT
                + f"""
                , permitted AS (
                    SELECT c.rowid AS ref, c.*, d.project_id, d.key, d.revision, d.title, d.published_at,
                        d.revision = r.latest AS current
                    FROM chunks c JOIN documents d ON c.document_id = d.id
                    {JOIN_CURRENT}
                    JOIN projects p ON d.project_id = p.id
                    WHERE {allowed} AND p.id IN ({placeholders})
                        AND (? = 0 OR d.revision = r.latest)
                        AND NOT EXISTS (
                            SELECT 1 FROM document_lifecycle life
                                WHERE (life.project_id, life.key) = (d.project_id, d.key)
                        )
                )
                SELECT id,document_id,project_id,key,revision,title,published_at,current,
                    heading,topic,decision,content,start_line,end_line
                FROM permitted WHERE {shortlist}
                ORDER BY julianday(published_at) DESC, start_line, id
                """,
                (*args, *scope, current_only, *parameters),
            ).fetchall()
        return [Evidence(**(dict(row) | {"current": bool(row["current"])})) for row in rows]

    def publish(
        self,
        project_id: str,
        key: str,
        title: str,
        body: str,
        *,
        access: Access | None = None,
        source_name: str = "",
        change_note: str = "",
        expected_revision: int | None = None,
        create_only: bool = False,
    ) -> str:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if access is not None:
                self._require_edit(conn, access, project_id)
            if create_only or isinstance(access, Account) or expected_revision is not None:
                latest = conn.execute(
                    "SELECT MAX(revision) FROM documents WHERE project_id=? AND key=?",
                    (project_id, key),
                ).fetchone()[0]
                if latest != (None if create_only else expected_revision):
                    raise Conflict("资料版本已变化。请重新打开当前版本后再发布。")
            if conn.execute(
                "SELECT 1 FROM document_lifecycle WHERE project_id = ? AND key = ?",
                (project_id, key),
            ).fetchone():
                raise Conflict("请先恢复已归档资料。")
            version = self._publish(
                conn, project_id, key, title, body, now(), source_name, change_note
            )
            if isinstance(access, Account):
                record_audit(conn, access, "document.published", version)
            return version

    @staticmethod
    def _require_edit(conn, access: Access, project_id: str) -> None:
        allowed, args = project_access(access, write=True)
        if not conn.execute(
            f"SELECT 1 FROM projects p WHERE p.id = ? AND {allowed}",
            (project_id, *args),
        ).fetchone():
            raise Denied("当前身份无法编辑该项目的资料。")

    def archive(self, access: Access, project_id: str, key: str, archive: bool) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_edit(conn, access, project_id)
            if not conn.execute(
                "SELECT 1 FROM documents WHERE project_id = ? AND key = ?",
                (project_id, key),
            ).fetchone():
                raise LookupError("未找到该资料。")
            if archive:
                changed = conn.execute(
                    "INSERT OR IGNORE INTO document_lifecycle VALUES (?, ?, ?)",
                    (project_id, key, now()),
                )
            else:
                changed = conn.execute(
                    "DELETE FROM document_lifecycle WHERE project_id = ? AND key = ?",
                    (project_id, key),
                )
            if changed.rowcount and isinstance(access, Account):
                action = "document.archived" if archive else "document.restored"
                record_audit(conn, access, action, f"{project_id}/{key}")

    @staticmethod
    def _publish(
        conn,
        project_id: str,
        key: str,
        title: str,
        body: str,
        date: str,
        source_name: str = "",
        change_note: str = "",
    ) -> str:
        sections = parse_markdown(body)
        revision = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM documents WHERE project_id = ? AND key = ?",
            (project_id, key),
        ).fetchone()[0]
        version_id = f"{project_id}--{key}@{revision}"
        conn.execute(
            "INSERT INTO documents (id,project_id,key,revision,title,body,published_at,source_name,change_note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version_id, project_id, key, revision, title, body, date, source_name, change_note),
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
        conn.executemany(
            "INSERT INTO chunk_index (rowid,terms) SELECT rowid, ? FROM chunks WHERE id = ?",
            [
                (
                    " ".join(tokens(f"{row.heading} {row.heading} {title} {row.content}")),
                    f"{version_id}:{i}",
                )
                for i, row in enumerate(sections, 1)
            ],
        )
        return version_id

    def session(
        self,
        session_id: str,
        mode: Mode,
        *,
        allow_expired_account: bool = False,
    ) -> Session | None:
        if not session_id:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT s.id, s.role, a.id AS account_id, a.username, a.name, a.admin
                FROM sessions s LEFT JOIN accounts a ON s.account_id = a.id AND a.enabled = 1
                WHERE s.id = ? AND s.mode = ?
                    AND (s.expires_at > ? OR (? AND a.id IS NOT NULL))
                    AND (s.mode != 'team' OR a.id IS NOT NULL)
                """,
                (session_id, mode, int(time.time()), allow_expired_account),
            ).fetchone()
        if not row:
            return None
        access: Access = row["role"]
        if row["account_id"]:
            access = Account(row["account_id"], row["username"], row["name"], bool(row["admin"]))
        return Session(session_id, mode, access)

    def add_session(self, session: Session, ttl: int) -> None:
        account = session.account
        role = ("reviewer" if account.admin else "member") if account else session.access
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM sessions WHERE expires_at <= ? AND (
                    account_id IS NULL OR NOT EXISTS (SELECT 1 FROM runs WHERE session_id = sessions.id)
                )
                """,
                (int(time.time()),),
            )
            conn.execute(
                """
                INSERT INTO sessions (id, role, expires_at, mode, account_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    role,
                    int(time.time()) + ttl,
                    session.mode,
                    account.id if account else None,
                ),
            )

    def remove_session(self, session_id: str, mode: Mode) -> None:
        with self.connect() as conn:
            if mode == "team":
                conn.execute(
                    "UPDATE sessions SET expires_at = 0 WHERE id = ? AND mode = ?",
                    (session_id, mode),
                )
            else:
                conn.execute("DELETE FROM sessions WHERE id = ? AND mode = ?", (session_id, mode))

    @staticmethod
    def owner(session: Session) -> tuple[str, tuple]:
        if session.account:
            return "s.account_id = ?", (session.account.id,)
        return "s.id = ?", (session.id,)

    @classmethod
    def visible_runs(cls, session: Session) -> tuple[str, tuple]:
        owner, args = cls.owner(session)
        if session.account is None:
            return owner, args
        allowed, grants = project_access(session.access)
        return (
            f"{owner} AND NOT EXISTS ("
            "SELECT 1 FROM json_each(r.scope) sc WHERE NOT EXISTS ("
            f"SELECT 1 FROM projects p WHERE p.id = sc.value AND {allowed}))",
            (*args, *grants),
        )

    def enqueue(
        self,
        session: Session,
        run_id: str,
        question: str,
        scope: list[str],
        capacity: int,
    ) -> None:
        owner, args = self.owner(session)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                "SELECT 1 FROM sessions WHERE id = ? AND expires_at > ?",
                (session.id, int(time.time())),
            ).fetchone():
                raise Denied("会话已失效，请重新登录。")
            if conn.execute(
                f"""
                SELECT 1 FROM runs r JOIN sessions s ON r.session_id = s.id
                WHERE {owner} AND r.status IN ('queued', 'running') LIMIT 1
                """,
                args,
            ).fetchone():
                raise Conflict("你已有一条排队或执行中的问答。")
            pending = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE status IN ('queued', 'running')",
            ).fetchone()[0]
            if pending >= capacity:
                raise QueueFull("运行队列已满，请稍后重试。")
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, 'queued', ?, NULL, NULL)",
                (run_id, session.id, question, json.dumps(scope), now()),
            )

    def claim(self, mode: Mode) -> dict | None:
        with self.connect() as conn:
            if not conn.execute("SELECT 1 FROM runs WHERE status='queued' LIMIT 1").fetchone():
                return None
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT r.id, r.session_id, r.question, r.scope
                FROM runs r JOIN sessions s ON r.session_id = s.id
                WHERE r.status = 'queued' AND s.mode = ? ORDER BY r.created_at, r.id LIMIT 1
                """,
                (mode,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (row["id"],))
            return dict(row) | {"scope": json.loads(row["scope"])}

    def cancel(self, run_id: str) -> bool:
        with self.connect() as conn:
            changed = conn.execute(
                "UPDATE runs SET status = 'cancelled' WHERE id = ? AND status IN ('queued','running')",
                (run_id,),
            )
            return bool(changed.rowcount)

    def add_event(self, run_id: str, stage: str, detail: str, elapsed_ms: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO events (run_id, stage, detail, elapsed_ms) VALUES (?, ?, ?, ?)",
                (run_id, stage, detail, elapsed_ms),
            )

    def finish_run(self, run_id: str, result: dict | None, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, result = ?, error = ? WHERE id = ? AND status = 'running'",
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

    def runs(self, session: Session) -> list[dict]:
        allowed, args = self.visible_runs(session)
        with self.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT r.id, r.question, r.status, r.created_at
                    FROM runs r JOIN sessions s ON s.id = r.session_id WHERE {allowed}
                    ORDER BY r.created_at DESC LIMIT 50
                    """,
                    args,
                )
            ]

    def run(self, session: Session, run_id: str) -> dict | None:
        allowed, args = self.visible_runs(session)
        with self.connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                f"""
                SELECT r.*, f.rating, f.note, f.resolved_at
                FROM runs r JOIN sessions s ON s.id = r.session_id
                LEFT JOIN feedback f ON f.run_id = r.id
                WHERE r.id = ? AND {allowed}
                """,
                (run_id, *args),
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
            "feedback": (
                {"rating": row["rating"], "note": row["note"], "resolved_at": row["resolved_at"]}
                if row["rating"]
                else None
            ),
            "events": [dict(event) for event in events],
        }

    def save_feedback(self, session: Session, run_id: str, rating: str, note: str) -> None:
        allowed, args = self.visible_runs(session)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                f"""
                SELECT 1 FROM runs r JOIN sessions s ON s.id = r.session_id
                WHERE r.id = ? AND r.status = 'done' AND {allowed}
                """,
                (run_id, *args),
            ).fetchone():
                raise LookupError("未找到可反馈的回答。")
            conn.execute(
                """
                INSERT INTO feedback (run_id,rating,note,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET rating = excluded.rating, note = excluded.note,
                    updated_at = excluded.updated_at, resolved_at = NULL
                """,
                (run_id, rating, note, now()),
            )

    def backup(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=False)
        try:
            with self.connect() as conn, closing(sqlite3.connect(target)) as dest:
                conn.backup(dest)
        except Exception:
            target.unlink(missing_ok=True)
            raise
