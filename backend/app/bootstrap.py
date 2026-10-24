from __future__ import annotations

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.database import ensure_sqlite_directory, sqlite_path
from app.models import Base, Item, User
from app.security import hash_password
from app.services.specs import dump_specs, specs_from_params

ADMIN_ACCOUNT = "admin"
ADMIN_PASSWORD = "admin"


def database_exists(url: str) -> bool:
    path = sqlite_path(url)
    if path is not None:
        return path.is_file()
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


def _ensure_is_admin_column(bind) -> None:
    inspector = inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    names = {column["name"] for column in inspector.get_columns("users")}
    if "is_admin" in names:
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))


def _ensure_specs_column(bind, session_factory) -> None:
    inspector = inspect(bind)
    if "items" not in inspector.get_table_names():
        return
    names = {column["name"] for column in inspector.get_columns("items")}
    if "specs" not in names:
        with bind.begin() as conn:
            conn.execute(text("ALTER TABLE items ADD COLUMN specs TEXT"))
    _backfill_specs(session_factory)


def _backfill_specs(session_factory) -> None:
    db = session_factory()
    try:
        items = db.scalars(select(Item)).all()
        changed = False
        for item in items:
            raw = item.specs
            if raw is not None and str(raw).strip() != "":
                continue
            item.specs = dump_specs(specs_from_params(item.category or "", item.params or ""))
            changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def _seed_admin(session_factory) -> None:
    db = session_factory()
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


def prepare_connection(bind, session_factory, url: str) -> None:
    fresh = not database_exists(url)
    if url.startswith("sqlite"):
        ensure_sqlite_directory(url)
    elif url.startswith("mysql") and fresh:
        _create_mysql_database(url)
    Base.metadata.create_all(bind)
    _ensure_is_admin_column(bind)
    _ensure_specs_column(bind, session_factory)
    if fresh or _admin_account_missing(session_factory):
        _seed_admin(session_factory)
    from app.services.system_config import ensure_settings

    ensure_settings(session_factory, url)


def prepare_database() -> None:
    import app.database as database

    prepare_connection(database.engine, database.SessionLocal, database.current_url)


def _admin_account_missing(session_factory) -> bool:
    db = session_factory()
    try:
        return db.scalar(select(User.id).where(User.email == ADMIN_ACCOUNT)) is None
    finally:
        db.close()
