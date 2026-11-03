from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

SECRET_FILE_NAME = "secret_key"


class Settings:
    def __init__(self) -> None:
        self.database_url = sqlite_only(os.getenv("DATABASE_URL", "sqlite:///./data/app.db"))
        self.secret_key = os.getenv("SECRET_KEY", "").strip() or load_or_create_secret(self.database_url)
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.cookie_name = "cms_session"
        self.cookie_secure = os.getenv("COOKIE_SECURE", "0") == "1"
        self.session_ttl = 14 * 24 * 3600
        self.static_dir = os.getenv("STATIC_DIR", "").strip()

    @property
    def ai_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


def sqlite_only(url: str) -> str:
    url = url.strip()
    if not url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL 只支持 SQLite，例如 sqlite:///./data/app.db")
    return url


def secret_file(database_url: str) -> Path:
    bare = database_url.split("?", 1)[0]
    if bare.startswith("sqlite:///") and ":memory:" not in bare and bare[len("sqlite:///") :]:
        return Path(bare[len("sqlite:///") :]).parent / SECRET_FILE_NAME
    return Path("data") / SECRET_FILE_NAME


def load_or_create_secret(database_url: str) -> str:
    path = secret_file(database_url)
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(key)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip() or key
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
