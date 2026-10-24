from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.database import SessionLocal, engine, ensure_sqlite_directory
from app.models import Base, User
from app.security import hash_password

ADMIN_ACCOUNT = "admin"
ADMIN_PASSWORD = "admin"


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    if ":memory:" in url.split("?", 1)[0]:
        return None
    raw = url.split("?", 1)[0][len("sqlite:///") :]
    if not raw:
        return None
    return Path(raw)


def database_exists(url: str) -> bool:
    sqlite_path = _sqlite_path(url)
    if sqlite_path is not None:
        return sqlite_path.is_file()
    if url.startswith("mysql"):
        return _mysql_database_exists(url)
    return True


def _mysql_database_exists(url: str) -> bool:
    parsed = make_url(url)
    database = parsed.database
    if not database:
        return True
    probe = create_engine(parsed.set(database="mysql"), pool_pre_ping=True)
    try:
        with probe.connect() as conn:
            found = conn.execute(
                text("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = :name"),
                {"name": database},
            ).first()
            return found is not None
    finally:
        probe.dispose()


def _create_mysql_database(url: str) -> None:
    parsed = make_url(url)
    database = parsed.database
    if not database:
        return
    ident = database.replace("`", "``")
    probe = create_engine(parsed.set(database="mysql"), pool_pre_ping=True)
    try:
        with probe.begin() as conn:
            conn.execute(text(f"CREATE DATABASE `{ident}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    finally:
        probe.dispose()


def _ensure_is_admin_column() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    names = {column["name"] for column in inspector.get_columns("users")}
    if "is_admin" in names:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))


def _seed_admin() -> None:
    db = SessionLocal()
    try:
        exists = db.scalar(select(User.id).where(User.email == ADMIN_ACCOUNT))
        if exists:
            return
        db.add(
            User(
                email=ADMIN_ACCOUNT,
                password_hash=hash_password(ADMIN_PASSWORD),
                is_admin=True,
            )
        )
        db.commit()
    finally:
        db.close()


def prepare_database() -> None:
    url = get_settings().database_url
    fresh = not database_exists(url)
    if url.startswith("sqlite"):
        ensure_sqlite_directory(url)
    elif url.startswith("mysql") and fresh:
        _create_mysql_database(url)
    Base.metadata.create_all(engine)
    _ensure_is_admin_column()
    if fresh or _admin_account_missing():
        _seed_admin()


def _admin_account_missing() -> bool:
    db = SessionLocal()
    try:
        return db.scalar(select(User.id).where(User.email == ADMIN_ACCOUNT)) is None
    finally:
        db.close()
