import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


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

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            db=Path(os.getenv("SCOPEBRIEF_DB", "data/scopebrief.db")),
            demo=os.getenv("SCOPEBRIEF_DEMO", "1") == "1",
            secure_cookie=os.getenv("SCOPEBRIEF_SECURE_COOKIE", "0") == "1",
            member_key=os.getenv("SCOPEBRIEF_MEMBER_KEY", ""),
            reviewer_key=os.getenv("SCOPEBRIEF_REVIEWER_KEY", ""),
            model_base_url=os.getenv("SCOPEBRIEF_MODEL_BASE_URL", "").rstrip("/"),
            model_name=os.getenv("SCOPEBRIEF_MODEL_NAME", ""),
            model_key=os.getenv("SCOPEBRIEF_MODEL_KEY", ""),
            model_timeout=float(os.getenv("SCOPEBRIEF_MODEL_TIMEOUT", "15")),
        )
