from __future__ import annotations

from sqlalchemy import select

from app.database import ensure_sqlite_directory
from app.models import Base, User, new_session_token
from app.security import hash_password
from app.services.spec_config import seed_defaults

ADMIN_ACCOUNT = "admin"
ADMIN_PASSWORD = "admin"


def _seed_admin(session_factory) -> None:
    """库里没有任何管理员时，创建 admin/admin，并要求首次登录后改密码。"""
    db = session_factory()
    try:
        if db.scalar(select(User.id).where(User.is_admin.is_(True)).limit(1)) is not None:
            return
        existing = db.scalar(select(User).where(User.email == ADMIN_ACCOUNT))
        if existing is not None:
            existing.is_admin = True
            db.commit()
            return
        user = User(
            email=ADMIN_ACCOUNT,
            password_hash=hash_password(ADMIN_PASSWORD),
            is_admin=True,
            must_change_password=True,
            session_token=new_session_token(),
        )
        db.add(user)
        db.flush()
        seed_defaults(db, user.id)
        db.commit()
    finally:
        db.close()


def prepare_connection(bind, session_factory, url: str) -> None:
    ensure_sqlite_directory(url)
    Base.metadata.create_all(bind)
    _seed_admin(session_factory)
    from app.services.images import cache_remote_item_images
    from app.services.system_config import ensure_settings

    ensure_settings(session_factory, url)
    cache_remote_item_images(session_factory, url)


def prepare_database() -> None:
    import app.database as database

    prepare_connection(database.engine, database.SessionLocal, database.current_url)
