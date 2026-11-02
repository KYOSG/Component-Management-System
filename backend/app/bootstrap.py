from __future__ import annotations

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url

from app.database import ensure_sqlite_directory, sqlite_path
from app.models import Base, Box, Item, ItemLocation, User, utcnow
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


def _column_names(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _ensure_specs_column(bind) -> None:
    if "specs" in _column_names(bind, "items") or not _column_names(bind, "items"):
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE items ADD COLUMN specs TEXT"))


def _ensure_unit_price_column(bind) -> None:
    if "unit_price" in _column_names(bind, "items") or not _column_names(bind, "items"):
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE items ADD COLUMN unit_price FLOAT"))


def _ensure_box_type_column(bind) -> None:
    if "box_type" in _column_names(bind, "boxes") or not _column_names(bind, "boxes"):
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE boxes ADD COLUMN box_type VARCHAR(16) NOT NULL DEFAULT 'grid'"))


def _ensure_slot_count_column(bind) -> None:
    if "slot_count" in _column_names(bind, "boxes") or not _column_names(bind, "boxes"):
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE boxes ADD COLUMN slot_count INTEGER NOT NULL DEFAULT 0"))


def _ensure_slot_index_column(bind) -> None:
    if "slot_index" in _column_names(bind, "item_locations") or not _column_names(bind, "item_locations"):
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE item_locations ADD COLUMN slot_index INTEGER"))


def _backfill_locations(bind, session_factory) -> None:
    item_columns = _column_names(bind, "items")
    if not item_columns or "item_locations" not in inspect(bind).get_table_names():
        return
    db = session_factory()
    try:
        existing = db.scalar(select(func.count()).select_from(ItemLocation)) or 0
        if existing:
            return
        if "box_id" in item_columns:
            rows = db.execute(text("SELECT id, user_id, quantity, box_id, row, col FROM items")).all()
        else:
            rows = db.execute(text("SELECT id, user_id, quantity, NULL, NULL, NULL FROM items")).all()
        now = utcnow()
        for item_id, user_id, quantity, box_id, row, col in rows:
            amount = quantity or 0
            placed = box_id and row and col
            if not placed and not amount:
                continue
            db.add(
                ItemLocation(
                    item_id=item_id,
                    user_id=user_id,
                    location_type="box_cell" if placed else "unboxed",
                    box_id=box_id if placed else None,
                    row=row if placed else None,
                    col=col if placed else None,
                    reel_label="",
                    quantity=amount,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()
    finally:
        db.close()


def _backfill_reel_slots(session_factory) -> None:
    db = session_factory()
    try:
        boxes = list(db.scalars(select(Box).where(Box.box_type == "reel")).all())
        changed = False
        for box in boxes:
            locs = list(
                db.scalars(
                    select(ItemLocation)
                    .where(ItemLocation.box_id == box.id, ItemLocation.location_type == "tape_reel")
                    .order_by(ItemLocation.id)
                ).all()
            )
            used = {loc.slot_index for loc in locs if loc.slot_index}
            nxt = 1
            for loc in locs:
                if loc.slot_index:
                    continue
                while nxt in used:
                    nxt += 1
                loc.slot_index = nxt
                if not (loc.reel_label or "").strip():
                    loc.reel_label = str(nxt)
                used.add(nxt)
                nxt += 1
                changed = True
            highest = max(used) if used else 0
            if (box.slot_count or 0) < highest:
                box.slot_count = highest
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


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
    _ensure_unit_price_column(bind)
    _ensure_box_type_column(bind)
    _ensure_slot_count_column(bind)
    _ensure_slot_index_column(bind)
    _backfill_locations(bind, session_factory)
    _backfill_reel_slots(session_factory)
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
