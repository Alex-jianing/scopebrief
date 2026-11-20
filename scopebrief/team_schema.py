TEAM_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE, name TEXT NOT NULL,
    password_hash TEXT NOT NULL, admin INTEGER NOT NULL, enabled INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_members (
    account_id TEXT NOT NULL REFERENCES accounts(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    role TEXT NOT NULL CHECK(role IN ('reader', 'editor')),
    PRIMARY KEY (account_id, project_id)
);
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
    grants TEXT NOT NULL, bootstrap INTEGER NOT NULL, issued_by TEXT REFERENCES accounts(id),
    created_at TEXT NOT NULL, expires_at INTEGER NOT NULL, used_by TEXT REFERENCES accounts(id)
);
CREATE TABLE IF NOT EXISTS auth_limits (
    key TEXT PRIMARY KEY, bucket INTEGER NOT NULL, attempts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS document_lifecycle (
    project_id TEXT NOT NULL REFERENCES projects(id), key TEXT NOT NULL,
    archived_at TEXT NOT NULL, PRIMARY KEY(project_id, key)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor_id TEXT REFERENCES accounts(id),
    action TEXT NOT NULL, target TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    rating TEXT NOT NULL CHECK(rating IN ('helpful', 'review')),
    note TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS review_cases (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, question TEXT NOT NULL, scope TEXT NOT NULL,
    expected_status TEXT NOT NULL, required_sources TEXT NOT NULL, phrase TEXT NOT NULL,
    feedback_run_id TEXT UNIQUE REFERENCES runs(id), created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS review_reports (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, body TEXT NOT NULL
);
"""

# Every access read rechecks the account and its current project assignment.
PROJECT_ACCESS = """
EXISTS (
    SELECT 1 FROM accounts a
    WHERE a.id = ? AND a.enabled = 1 AND (
        a.admin = 1 OR EXISTS (
            SELECT 1 FROM project_members m WHERE m.account_id = a.id
                AND m.project_id = p.id AND (? = 0 OR m.role = 'editor')
        )
    )
)
"""
