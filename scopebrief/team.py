import json
import re
import secrets
import sqlite3
import time

from .identity import Account, Conflict, Denied, QueueFull, digest, hash_password, verify_password
from .store import Store, now, record_audit

USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,39}")
INVITE_TTL = 72 * 60 * 60


def require_admin(conn, actor: Account) -> None:
    if not conn.execute(
        "SELECT 1 FROM accounts WHERE id = ? AND enabled = 1 AND admin = 1",
        (actor.id,),
    ).fetchone():
        raise Denied("需要团队管理员身份。")


def validate_registration(username: str, name: str, password: str) -> tuple[str, str]:
    username, name = username.strip().lower(), name.strip()
    if not USERNAME.fullmatch(username):
        raise ValueError("用户名须为 3–40 位小写字母、数字、点、下划线或连字符。")
    if not 2 <= len(name) <= 60:
        raise ValueError("显示名称须为 2–60 字。")
    if not 12 <= len(password) <= 128:
        raise ValueError("密码须为 12–128 个字符。")
    return username, name


def account(row) -> Account:
    return Account(row["id"], row["username"], row["name"], bool(row["admin"]))


class Team:
    def __init__(self, store: Store):
        self.store = store

    def throttle(self, address: str) -> None:
        bucket = int(time.time()) // 600
        key = digest(address)
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM auth_limits WHERE bucket < ?", (bucket - 1,))
            row = conn.execute(
                """
                INSERT INTO auth_limits VALUES (?, ?, 1)
                ON CONFLICT(key) DO UPDATE SET
                    attempts = CASE WHEN bucket = excluded.bucket THEN attempts + 1 ELSE 1 END,
                    bucket = excluded.bucket
                RETURNING attempts
                """,
                (key, bucket),
            ).fetchone()
        if row[0] > 30:
            raise QueueFull("尝试过多，请稍后再试。")

    def authenticate(self, username: str, password: str) -> Account | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username.strip().lower(),)
            ).fetchone()
        if (
            not verify_password(password, row["password_hash"] if row else None)
            or not row["enabled"]
        ):
            return None
        return account(row)

    def issue(
        self,
        actor: Account | None,
        label: str,
        grants: dict[str, str],
        *,
        bootstrap: bool = False,
    ) -> dict:
        code, invitation_id = secrets.token_urlsafe(24), secrets.token_hex(12)
        expires_at = int(time.time()) + (24 * 60 * 60 if bootstrap else INVITE_TTL)
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if bootstrap:
                if conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
                    raise Conflict("团队已有管理员。")
                conn.execute(
                    "UPDATE invitations SET expires_at = 0 WHERE bootstrap = 1 AND used_by IS NULL"
                )
            else:
                if actor is None:
                    raise Denied("需要团队管理员身份。")
                require_admin(conn, actor)
                self._check_grants(conn, grants)
            conn.execute(
                """
                INSERT INTO invitations (id,code_hash,label,grants,bootstrap,issued_by,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    invitation_id,
                    digest(code),
                    label,
                    json.dumps(grants),
                    bootstrap,
                    actor.id if actor else None,
                    now(),
                    expires_at,
                ),
            )
            record_audit(conn, actor, "invite.issued", invitation_id)
        return {"id": invitation_id, "code": code, "expires_at": expires_at}

    def redeem(self, code: str, username: str, name: str, password: str) -> Account:
        username, name = validate_registration(username, name, password)
        encoded = hash_password(password)
        proposed = Account(secrets.token_hex(16), username, name, False)
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            invitation = conn.execute(
                "SELECT * FROM invitations WHERE code_hash = ? AND used_by IS NULL AND expires_at > ?",
                (digest(code.strip()), int(time.time())),
            ).fetchone()
            if not invitation:
                raise Denied("邀请码已失效或已被使用。")
            if (
                invitation["bootstrap"]
                and conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone()
            ):
                raise Denied("团队管理员已完成初始化。")
            created = Account(proposed.id, username, name, bool(invitation["bootstrap"]))
            try:
                conn.execute(
                    "INSERT INTO accounts VALUES (?,?,?,?,?,1,?)",
                    (created.id, created.username, created.name, encoded, created.admin, now()),
                )
            except sqlite3.IntegrityError as exc:
                raise Conflict("用户名已被使用。") from exc
            self._replace_grants(conn, created.id, json.loads(invitation["grants"]))
            conn.execute(
                "UPDATE invitations SET used_by = ? WHERE id = ?", (created.id, invitation["id"])
            )
            record_audit(conn, created, "account.activated", created.username)
        return created

    def reset_password(self, username: str, password: str) -> None:
        if not 12 <= len(password) <= 128:
            raise ValueError("密码须为 12–128 个字符。")
        encoded = hash_password(password)
        with self.store.connect() as conn:
            row = conn.execute("SELECT id FROM accounts WHERE username = ?", (username,)).fetchone()
            if row is None:
                raise LookupError("未找到该账号。")
            conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (encoded, row["id"]))
            conn.execute("UPDATE sessions SET expires_at = 0 WHERE account_id = ?", (row["id"],))
            record_audit(conn, None, "account.password_reset", username)

    def projects(
        self,
        actor: Account,
        project_id: str,
        name: str,
        description: str,
        aliases: list[str],
        color: str,
    ) -> None:
        names = list(dict.fromkeys([name, project_id, *aliases]))
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            other = conn.execute(
                "SELECT aliases FROM projects WHERE id != ?", (project_id,)
            ).fetchall()
            existing_aliases = {
                alias.casefold() for row in other for alias in json.loads(row["aliases"])
            }
            if any(alias.casefold() in existing_aliases for alias in names):
                raise Conflict("项目名称或别名与现有项目重复。")
            conn.execute(
                """
                INSERT INTO projects (id,name,description,color,aliases,reviewer_only)
                VALUES (?,?,?,?,?,0)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description,
                    color=excluded.color, aliases=excluded.aliases
                """,
                (project_id, name, description, color, json.dumps(names, ensure_ascii=False)),
            )
            record_audit(conn, actor, "project.saved", project_id)

    def update_member(
        self, actor: Account, member_id: str, enabled: bool, grants: dict[str, str]
    ) -> None:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            member = conn.execute(
                "SELECT id, username, admin FROM accounts WHERE id = ?", (member_id,)
            ).fetchone()
            if not member:
                raise LookupError("未找到该账号。")
            if member["admin"]:
                raise Denied("管理员权限由团队初始化和运维命令管理。")
            self._check_grants(conn, grants)
            self._replace_grants(conn, member_id, grants)
            conn.execute("UPDATE accounts SET enabled = ? WHERE id = ?", (enabled, member_id))
            if not enabled:
                conn.execute(
                    "UPDATE sessions SET expires_at = 0 WHERE account_id = ?", (member_id,)
                )
            record_audit(conn, actor, "member.updated", member["username"])

    def revoke(self, actor: Account, invitation_id: str) -> None:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            require_admin(conn, actor)
            if not conn.execute(
                "UPDATE invitations SET expires_at=0 WHERE id=? AND used_by IS NULL",
                (invitation_id,),
            ).rowcount:
                raise LookupError("未找到可撤销的邀请。")
            record_audit(conn, actor, "invite.revoked", invitation_id)

    @staticmethod
    def _check_grants(conn, grants: dict[str, str]) -> None:
        project_ids = {row[0] for row in conn.execute("SELECT id FROM projects")}
        if not grants.keys() <= project_ids or any(
            role not in {"reader", "editor"} for role in grants.values()
        ):
            raise ValueError("项目权限配置有误。")

    @staticmethod
    def _replace_grants(conn, account_id: str, grants: dict[str, str]) -> None:
        conn.execute("DELETE FROM project_members WHERE account_id = ?", (account_id,))
        conn.executemany(
            "INSERT INTO project_members VALUES (?,?,?)",
            [(account_id, pid, role) for pid, role in grants.items()],
        )

    def overview(self, actor: Account) -> dict:
        with self.store.connect() as conn:
            conn.execute("BEGIN")
            require_admin(conn, actor)
            projects = [
                dict(row) | {"aliases": json.loads(row["aliases"])}
                for row in conn.execute(
                    "SELECT id,name,description,color,aliases FROM projects ORDER BY rowid"
                )
            ]
            grants: dict[str, dict] = {}
            for row in conn.execute("SELECT account_id,project_id,role FROM project_members"):
                grants.setdefault(row["account_id"], {})[row["project_id"]] = row["role"]
            members = [
                account(row).public()
                | {"enabled": bool(row["enabled"]), "grants": grants.get(row["id"], {})}
                for row in conn.execute(
                    "SELECT id,username,name,admin,enabled FROM accounts ORDER BY username"
                )
            ]
            invitations = [
                dict(row) | {"grants": json.loads(row["grants"])}
                for row in conn.execute(
                    """
                    SELECT id,label,grants,created_at,expires_at,used_by FROM invitations
                    WHERE bootstrap = 0 ORDER BY created_at DESC LIMIT 40
                    """
                )
            ]
            activity = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT e.id,e.at,a.name AS actor,e.action,e.target
                    FROM audit e LEFT JOIN accounts a ON a.id = e.actor_id ORDER BY e.id DESC LIMIT 60
                    """
                )
            ]
        return {
            "projects": projects,
            "members": members,
            "invitations": invitations,
            "activity": activity,
        }
