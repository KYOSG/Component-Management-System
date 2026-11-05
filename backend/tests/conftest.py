import os
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "_test.sqlite"
if DB_PATH.exists():
    DB_PATH.unlink()
for leftover in (DB_PATH.parent / "active_database.json", DB_PATH.parent / "active_database.json.tmp"):
    if leftover.exists():
        leftover.unlink()

os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.as_posix()
os.environ["SECRET_KEY"] = "test-secret"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["STATIC_DIR"] = ""
os.environ["LCSC_REFRESH_WORKER"] = "0"

import pytest
from fastapi.testclient import TestClient

from app.main import app


def prepare_test_database() -> None:
    """测试默认打开注册，并跳过初始管理员的强制改密。"""
    from sqlalchemy import update

    import app.database as database
    from app.models import SystemConfig, User, utcnow
    from app.ratelimit import login_limiter

    login_limiter.reset()
    db = database.SessionLocal()
    try:
        row = db.get(SystemConfig, "allow_register")
        if row is None:
            db.add(SystemConfig(key="allow_register", value="1", updated_at=utcnow()))
        else:
            row.value = "1"
        db.execute(update(User).where(User.email == "admin").values(must_change_password=False))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        prepare_test_database()
        yield test_client
