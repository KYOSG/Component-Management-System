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

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
