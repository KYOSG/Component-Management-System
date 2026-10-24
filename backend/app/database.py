from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def ensure_sqlite_directory(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    raw = url[len("sqlite:///") :]
    if not raw or raw.startswith(":memory:"):
        return
    path = Path(raw)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)


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


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
