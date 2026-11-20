import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Literal

Role = Literal["member", "reviewer"]
Mode = Literal["demo", "shared", "team"]
ProjectRole = Literal["reader", "editor"]


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    name: str
    admin: bool

    def public(self) -> dict:
        return {"id": self.id, "username": self.username, "name": self.name, "admin": self.admin}


Access = Role | Account


@dataclass(frozen=True)
class Session:
    id: str
    mode: Mode
    access: Access

    @property
    def account(self) -> Account | None:
        return self.access if isinstance(self.access, Account) else None


class Denied(Exception):
    pass


class Conflict(Exception):
    pass


class QueueFull(Exception):
    pass


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 2**20)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return salt.hex() + ":" + _derive(password, salt).hex()


def verify_password(password: str, stored: str | None) -> bool:
    salt_hex, hash_hex = stored.split(":", 1) if stored else ("00" * 16, "00" * 64)
    match = hmac.compare_digest(_derive(password, bytes.fromhex(salt_hex)), bytes.fromhex(hash_hex))
    return stored is not None and match
