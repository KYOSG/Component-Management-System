from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
        self.secret_key = os.getenv("SECRET_KEY", "dev-change-me")
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
