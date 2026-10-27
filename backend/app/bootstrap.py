from __future__ import annotations

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.database import ensure_sqlite_directory, sqlite_path
from app.models import Base, Item, User
from app.security import hash_password
from app.services.spec_config import load_catalog, seed_defaults
from app.services.specs import dump_specs, load_specs, parse_params

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


def _ensure_specs_column(bind) -> None:
    inspector = inspect(bind)
    if "items" not in inspector.get_table_names():
        return
    names = {column["name"] for column in inspector.get_columns("items")}
    if "specs" not in names:
        with bind.begin() as conn:
            conn.execute(text("ALTER TABLE items ADD COLUMN specs TEXT"))


def _backfill_specs(session_factory) -> None:
    db = session_factory()
    try:
        items = db.scalars(select(Item)).all()
        catalogs = {}
        changed = False
        for item in items:
            catalog = catalogs.get(item.user_id)
            if catalog is None:
                catalog = load_catalog(db, item.user_id)
                catalogs[item.user_id] = catalog
            raw = item.specs
            category = item.category or ""
            params = item.params or ""
            if raw is None or str(raw).strip() == "":
                item.specs = dump_specs(catalog.extract(category, parse_params(params)))
                changed = True
                continue
            stored = load_specs(raw)
            shown = catalog.present(category, stored, params)
            if shown != stored:
                item.specs = dump_specs(shown)
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
        user = User(
            email=ADMIN_ACCOUNT,
            password_hash=hash_password(ADMIN_PASSWORD),
            is_admin=True,
        )
        db.add(user)
        db.flush()
        seed_defaults(db, user.id)
        db.commit()
    finally:
        db.close()


def _seed_missing_catalogs(session_factory) -> None:
    db = session_factory()
    try:
        user_ids = list(db.scalars(select(User.id)).all())
        for user_id in user_ids:
            seed_defaults(db, user_id)
        db.commit()
    finally:
        db.close()


def prepare_connection(bind, session_factory, url: str) -> None:
    fresh = not database_exists(url)
    categories_existed = "spec_categories" in inspect(bind).get_table_names() if not fresh else False
    if url.startswith("sqlite"):
        ensure_sqlite_directory(url)
    elif url.startswith("mysql") and fresh:
        _create_mysql_database(url)
    Base.metadata.create_all(bind)
    _ensure_is_admin_column(bind)
    _ensure_specs_column(bind)
    if fresh or _admin_account_missing(session_factory):
        _seed_admin(session_factory)
    if not categories_existed:
        _seed_missing_catalogs(session_factory)
    _backfill_specs(session_factory)
    from app.services.images import cache_remote_item_images
    from app.services.system_config import ensure_settings

    ensure_settings(session_factory, url)
    cache_remote_item_images(session_factory, url)


def prepare_database() -> None:
    import app.database as database

    prepare_connection(database.engine, database.SessionLocal, database.current_url)


def _admin_account_missing(session_factory) -> bool:
    db = session_factory()
    try:
        return db.scalar(select(User.id).where(User.email == ADMIN_ACCOUNT)) is None
    finally:
        db.close()
