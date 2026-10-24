from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def ensure_sqlite_directory(url: str) -> None:
    path = sqlite_path(url)
    if path is None:
        return
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)


def sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    bare = url.split("?", 1)[0]
    if ":memory:" in bare:
        return None
    raw = bare[len("sqlite:///") :]
    if not raw:
        return None
    return Path(raw)


def sqlite_url(location: str, name: str) -> str:
    return "sqlite:///" + (Path(location) / name).as_posix()


def split_sqlite(url: str) -> tuple[str, str]:
    path = sqlite_path(url)
    if path is None:
        raise ValueError("当前数据库不是 SQLite 文件")
    return str(path.parent), path.name


def same_sqlite(left: str, right: str) -> bool:
    left_path = sqlite_path(left)
    right_path = sqlite_path(right)
    if left_path is None or right_path is None:
        return False
    return left_path.resolve() == right_path.resolve()


def pointer_file(env_url: str | None = None) -> Path:
    url = get_settings().database_url if env_url is None else env_url
    path = sqlite_path(url)
    if path is None:
        return Path("data") / "active_database.json"
    return path.parent / "active_database.json"


def startup_url() -> str:
    fallback = get_settings().database_url
    path = pointer_file(fallback)
    if not path.is_file():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(data, dict):
        return fallback
    location = str(data.get("database_location") or "").strip()
    name = str(data.get("database_name") or "").strip()
    if not location or not name:
        return fallback
    return sqlite_url(location, name)


def write_pointer(location: str, name: str) -> None:
    path = pointer_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps({"database_location": location, "database_name": name}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def make_engine(url: str | None = None):
    database_url = url or get_settings().database_url
    ensure_sqlite_directory(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_conn, _record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


current_url = startup_url()
engine = make_engine(current_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def install_engine(url: str, new_engine: Engine, new_session: sessionmaker) -> Engine:
    global engine, SessionLocal, current_url
    previous = engine
    engine = new_engine
    SessionLocal = new_session
    current_url = url
    return previous


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
