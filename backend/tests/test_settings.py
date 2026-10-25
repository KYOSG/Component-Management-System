from fastapi.testclient import TestClient

from app.main import app


def test_ai_test_sends_prompt_and_returns_output(client, monkeypatch):
    class _Response:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "模型回复"}}]}

    def fake_post(url, **kwargs):
        assert url == "https://api.deepseek.com/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        assert kwargs["json"]["model"] == "deepseek-chat"
        assert kwargs["json"]["messages"] == [{"role": "user", "content": "你好"}]
        return _Response()

    monkeypatch.setattr("app.services.deepseek.httpx.post", fake_post)
    admin = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert admin.status_code == 200, admin.text
    response = client.post(
        "/api/settings/ai-test",
        json={
            "prompt": "你好",
            "deepseek_api_key": "sk-test",
            "deepseek_base_url": "https://api.deepseek.com",
            "deepseek_model": "deepseek-chat",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["output"] == "模型回复"
    missing = client.post("/api/settings/ai-test", json={"prompt": "你好", "deepseek_api_key": ""})
    assert missing.status_code == 400
    assert "API Key" in missing.json()["detail"]


def test_import_releases_database_before_ai(client, monkeypatch):
    import sqlite3

    from tests.conftest import DB_PATH
    from tests.samples import EDA_FILE

    admin = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert admin.status_code == 200, admin.text
    current = client.get("/api/settings").json()
    saved = client.put("/api/settings", json={**current, "deepseek_api_key": "sk-test"})
    assert saved.status_code == 200, saved.text
    box = client.post("/api/boxes", json={"name": "锁测试盒", "rows": 2, "cols": 2}).json()
    created = client.post(
        "/api/items",
        json={"mpn": "LOCK-TEST", "footprint": "0603", "value": "1uF", "quantity": 10, "box_id": box["id"], "row": 1, "col": 1},
    )
    assert created.status_code == 200, created.text
    called = {"count": 0}

    def fake_suggest(lines, **_kwargs):
        called["count"] += 1
        conn = sqlite3.connect(DB_PATH, timeout=0.5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        finally:
            conn.close()
        return {int(row["line_id"]): None for row in lines}

    monkeypatch.setattr("app.services.match.suggest", fake_suggest)
    try:
        imported = client.post(
            "/api/projects/import",
            files={"file": (EDA_FILE.name, EDA_FILE.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["ai_enabled"] is True
        assert called["count"] == 0
        with client.stream("GET", f"/api/projects/{imported.json()['id']}/recommend") as response:
            assert response.status_code == 200, response.text
            body = "".join(response.iter_text())
        assert called["count"] == 1
        assert "event: done" in body
        assert "event: line" in body
    finally:
        cleared = client.put("/api/settings", json={**current, "deepseek_api_key": ""})
        assert cleared.status_code == 200, cleared.text


def test_settings_require_admin(client):
    created = client.post("/api/auth/register", json={"email": "plain@example.com", "password": "secret1"})
    assert created.status_code == 200, created.text
    assert client.get("/api/settings").status_code == 403
    assert client.put(
        "/api/settings",
        json={"database_location": "data", "database_name": "other.db"},
    ).status_code == 403
    assert client.post("/api/settings/ai-test", json={"prompt": "你好", "deepseek_api_key": "sk"}).status_code == 403


def test_settings_reject_invalid_names(client, tmp_path):
    admin = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert admin.status_code == 200, admin.text
    current = client.get("/api/settings")
    assert current.status_code == 200, current.text
    assert current.json()["database_name"] == "_test.sqlite"
    blocked = client.put("/api/settings", json={"database_location": "", "database_name": "app.db"})
    assert blocked.status_code == 400
    blocked = client.put("/api/settings", json={"database_location": str(tmp_path), "database_name": "notes.txt"})
    assert blocked.status_code == 400
    blocked = client.put("/api/settings", json={"database_location": str(tmp_path), "database_name": "../app.db"})
    assert blocked.status_code == 400
    not_dir = tmp_path / "file"
    not_dir.write_text("x", encoding="utf-8")
    blocked = client.put("/api/settings", json={"database_location": str(not_dir), "database_name": "app.db"})
    assert blocked.status_code == 400
    assert client.get("/api/settings").json()["database_name"] == "_test.sqlite"


def test_admin_can_switch_database(client, tmp_path):
    from sqlalchemy.orm import sessionmaker

    import app.database as database

    admin = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert admin.status_code == 200, admin.text
    before_url = database.current_url
    target = tmp_path / "library"
    try:
        switched = client.put(
            "/api/settings",
            json={"database_location": str(target), "database_name": "next.db"},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["database_name"] == "next.db"
        assert (target / "next.db").is_file()
        assert database.pointer_file().is_file()
        assert client.get("/api/settings").json() == {
            "database_location": str(target),
            "database_name": "next.db",
            "deepseek_api_key": "",
            "deepseek_base_url": "https://api.deepseek.com",
            "deepseek_model": "deepseek-chat",
        }
        assert client.get("/api/auth/me").json()["email"] == "admin"
        assert client.get("/api/items").json()["total"] == 0
        with TestClient(app) as fresh:
            fresh.post("/api/auth/login", json={"email": "admin", "password": "admin"})
            assert fresh.get("/api/items").json()["total"] == 0
    finally:
        if not database.same_sqlite(database.current_url, before_url):
            restored = database.make_engine(before_url)
            restored_session = sessionmaker(bind=restored, autoflush=False, expire_on_commit=False)
            previous = database.install_engine(before_url, restored, restored_session)
            previous.dispose()
        pointer = database.pointer_file()
        if pointer.exists():
            pointer.unlink()
        temporary = pointer.with_name(pointer.name + ".tmp")
        if temporary.exists():
            temporary.unlink()
        assert database.same_sqlite(database.current_url, before_url)


def test_ai_settings_are_stored_and_enable_matching(client, monkeypatch):
    monkeypatch.setattr("app.services.match.suggest", lambda lines, **_kwargs: {})
    admin = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert admin.status_code == 200, admin.text
    current = client.get("/api/settings").json()
    assert current["deepseek_base_url"] == "https://api.deepseek.com"
    assert current["deepseek_model"] == "deepseek-chat"
    saved = client.put(
        "/api/settings",
        json={
            **current,
            "deepseek_api_key": "sk-test",
            "deepseek_base_url": "https://example.com/v1/",
            "deepseek_model": "deepseek-reasoner",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["deepseek_api_key"] == "sk-test"
    assert saved.json()["deepseek_base_url"] == "https://example.com/v1"
    assert saved.json()["deepseek_model"] == "deepseek-reasoner"
    try:
        from tests.samples import QUOTE_FILE

        imported = client.post(
            "/api/projects/import",
            files={"file": (QUOTE_FILE.name, QUOTE_FILE.read_bytes(), "application/vnd.ms-excel")},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["ai_enabled"] is True
        rejected = client.put("/api/settings", json={**current, "deepseek_base_url": "ftp://nope"})
        assert rejected.status_code == 400
        assert client.get("/api/settings").json()["deepseek_api_key"] == "sk-test"
    finally:
        cleared = client.put("/api/settings", json={**current, "deepseek_api_key": ""})
        assert cleared.status_code == 200, cleared.text
        assert client.get("/api/settings").json()["deepseek_api_key"] == ""
