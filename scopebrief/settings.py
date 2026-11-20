import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .identity import Mode


@dataclass(frozen=True)
class Settings:
    db: Path = Path("data/scopebrief.db")
    demo: bool = True
    secure_cookie: bool = False
    member_key: str = field(default="", repr=False)
    reviewer_key: str = field(default="", repr=False)
    model_base_url: str = ""
    model_name: str = ""
    model_key: str = field(default="", repr=False)
    model_timeout: float = 15

    @property
    def mode(self) -> Mode:
        if self.demo:
            return "demo"
        return "shared" if self.member_key or self.reviewer_key else "team"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        demo = os.getenv("SCOPEBRIEF_DEMO", "1") == "1"
        member_key = os.getenv("SCOPEBRIEF_MEMBER_KEY", "")
        reviewer_key = os.getenv("SCOPEBRIEF_REVIEWER_KEY", "")
        default_db = "data/scopebrief.db" if demo or member_key or reviewer_key else "data/team.db"
        return cls(
            db=Path(os.getenv("SCOPEBRIEF_DB") or default_db),
            demo=demo,
            secure_cookie=os.getenv("SCOPEBRIEF_SECURE_COOKIE", "0") == "1",
            member_key=member_key,
            reviewer_key=reviewer_key,
            model_base_url=os.getenv("SCOPEBRIEF_MODEL_BASE_URL", "").rstrip("/"),
            model_name=os.getenv("SCOPEBRIEF_MODEL_NAME", ""),
            model_key=os.getenv("SCOPEBRIEF_MODEL_KEY", ""),
            model_timeout=float(os.getenv("SCOPEBRIEF_MODEL_TIMEOUT", "15")),
        )
