from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.database as database
from app.config import get_settings
from app.models import SystemConfig, utcnow

DATABASE_LOCATION = "database_location"
DATABASE_NAME = "database_name"
DEEPSEEK_API_KEY = "deepseek_api_key"
DEEPSEEK_BASE_URL = "deepseek_base_url"
DEEPSEEK_MODEL = "deepseek_model"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
_CONFIG_KEYS = (
    DATABASE_LOCATION,
    DATABASE_NAME,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
)
_lock = threading.Lock()


@dataclass
class SystemSettings:
    database_location: str
    database_name: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str

    @property
    def ai_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


class DatabaseSwitchError(Exception):
    pass


def normalize_ai(api_key: str, base_url: str, model: str) -> tuple[str, str, str]:
    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip().rstrip("/") or DEFAULT_BASE_URL
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise DatabaseSwitchError("接口地址需要以 http:// 或 https:// 开头")
    model = (model or "").strip() or DEFAULT_MODEL
    return api_key, base_url, model


def _env_ai() -> tuple[str, str, str]:
    settings = get_settings()
    return settings.deepseek_api_key, settings.deepseek_base_url or DEFAULT_BASE_URL, settings.deepseek_model or DEFAULT_MODEL


def read_settings(db: Session) -> SystemSettings:
    rows = db.scalars(select(SystemConfig).where(SystemConfig.key.in_(_CONFIG_KEYS))).all()
    found = {row.key: row.value for row in rows}
    location = found.get(DATABASE_LOCATION) or ""
    name = found.get(DATABASE_NAME) or ""
    if not location or not name:
        try:
            fallback_location, fallback_name = database.split_sqlite(database.current_url)
        except ValueError as exc:
            raise DatabaseSwitchError("当前数据库不是 SQLite 文件") from exc
        location = location or fallback_location
        name = name or fallback_name
    env_key, env_url, env_model = _env_ai()
    return SystemSettings(
        database_location=location,
        database_name=name,
        deepseek_api_key=found[DEEPSEEK_API_KEY] if DEEPSEEK_API_KEY in found else env_key,
        deepseek_base_url=found[DEEPSEEK_BASE_URL] if DEEPSEEK_BASE_URL in found else env_url,
        deepseek_model=found[DEEPSEEK_MODEL] if DEEPSEEK_MODEL in found else env_model,
    )


def write_settings(db: Session, settings: SystemSettings) -> None:
    now = utcnow()
    values = {
        DATABASE_LOCATION: settings.database_location,
        DATABASE_NAME: settings.database_name,
        DEEPSEEK_API_KEY: settings.deepseek_api_key,
        DEEPSEEK_BASE_URL: settings.deepseek_base_url,
        DEEPSEEK_MODEL: settings.deepseek_model,
    }
    for key, value in values.items():
        row = db.get(SystemConfig, key)
        if row is None:
            db.add(SystemConfig(key=key, value=value, updated_at=now))
        else:
            row.value = value
            row.updated_at = now
    db.commit()


def ensure_settings(session_factory: sessionmaker, url: str) -> None:
    defaults: dict[str, str] = {}
    try:
        location, name = database.split_sqlite(url)
    except ValueError:
        location = name = ""
    else:
        defaults[DATABASE_LOCATION] = location
        defaults[DATABASE_NAME] = name
    env_key, env_url, env_model = _env_ai()
    defaults[DEEPSEEK_API_KEY] = env_key
    defaults[DEEPSEEK_BASE_URL] = env_url
    defaults[DEEPSEEK_MODEL] = env_model
    db = session_factory()
    try:
        existing = set(db.scalars(select(SystemConfig.key)).all())
        now = utcnow()
        for key, value in defaults.items():
            if key not in existing:
                db.add(SystemConfig(key=key, value=value, updated_at=now))
        db.commit()
    finally:
        db.close()


def switch_database(settings: SystemSettings, db: Session | None = None) -> SystemSettings:
    location = (settings.database_location or "").strip()
    name = (settings.database_name or "").strip()
    if not location:
        raise DatabaseSwitchError("请填写数据库位置")
    if Path(name).name != name or name in {".", ".."} or any(part in name for part in ("/", "\\", ":")):
        raise DatabaseSwitchError("数据库名字只能是文件名")
    parent = Path(location)
    if parent.exists() and not parent.is_dir():
        raise DatabaseSwitchError("数据库位置需要是目录")
    api_key, base_url, model = normalize_ai(settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model)
    url = database.sqlite_url(location, name)
    if not database.same_sqlite(url, database.current_url):
        if not name.lower().endswith(".db") or not Path(name).stem:
            raise DatabaseSwitchError("数据库名字需要以 .db 结尾")
    stored = SystemSettings(location, name, api_key, base_url, model)
    with _lock:
        if database.same_sqlite(url, database.current_url):
            if db is None:
                owned = database.SessionLocal()
                try:
                    write_settings(owned, stored)
                finally:
                    owned.close()
            else:
                write_settings(db, stored)
            try:
                database.write_pointer(location, name)
            except OSError as exc:
                raise DatabaseSwitchError(f"无法保存数据库位置：{exc}") from exc
            return stored
        new_engine = database.make_engine(url)
        new_session = sessionmaker(bind=new_engine, autoflush=False, expire_on_commit=False)
        try:
            from app.bootstrap import prepare_connection

            prepare_connection(new_engine, new_session, url)
            held = new_session()
            try:
                write_settings(held, stored)
            finally:
                held.close()
            try:
                database.write_pointer(location, name)
            except OSError as exc:
                raise DatabaseSwitchError(f"无法保存数据库位置：{exc}") from exc
        except DatabaseSwitchError:
            new_engine.dispose()
            raise
        except Exception as exc:
            new_engine.dispose()
            raise DatabaseSwitchError(f"无法切换到目标数据库：{exc}") from exc
        previous = database.install_engine(url, new_engine, new_session)
        previous.dispose()
        return stored
