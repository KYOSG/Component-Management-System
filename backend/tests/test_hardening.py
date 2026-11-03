import io
import zipfile

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api import _quote_workbook, register


def _login(client, email, password="secret1"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _admin(client):
    response = _login(client, "admin", "admin")
    assert response.status_code == 200, response.text
    return client


def _set_line(line_id, status, item_id):
    import app.database as database
    from app.models import ProjectLine

    db = database.SessionLocal()
    try:
        line = db.get(ProjectLine, line_id)
        line.match_status = status
        line.matched_item_id = item_id
        db.commit()
    finally:
        db.close()


def test_deleted_user_cookie_does_not_reach_new_account(client):
    register(client, "gone@example.com")
    gone_id = client.get("/api/auth/me").json()["id"]
    stale = client.cookies.get("cms_session")
    assert stale
    with TestClient(app) as admin:
        _admin(admin)
        assert admin.delete(f"/api/users/{gone_id}").status_code == 200
        created = admin.post("/api/users", json={"email": "heir@example.com", "password": "secret1", "is_admin": False})
        assert created.status_code == 200, created.text
    with TestClient(app) as replay:
        replay.cookies.set("cms_session", stale)
        assert replay.get("/api/auth/me").status_code == 401
        assert replay.get("/api/items").status_code == 401


def test_password_change_signs_out_other_sessions(client):
    register(client, "rotate@example.com")
    with TestClient(app) as second:
        assert _login(second, "rotate@example.com").status_code == 200
        assert second.get("/api/auth/me").status_code == 200
        changed = client.post("/api/auth/password", json={"old_password": "secret1", "new_password": "secret2"})
        assert changed.status_code == 200, changed.text
        assert client.get("/api/auth/me").status_code == 200
        assert second.get("/api/auth/me").status_code == 401
    wrong = client.post("/api/auth/password", json={"old_password": "nope", "new_password": "secret3"})
    assert wrong.status_code == 400


def test_registration_switch(client):
    assert client.get("/api/auth/options").json() == {"allow_register": True}
    _admin(client)
    current = client.get("/api/settings").json()
    try:
        closed = client.put("/api/settings", json={**current, "allow_register": False})
        assert closed.status_code == 200, closed.text
        assert closed.json()["allow_register"] is False
        assert client.get("/api/auth/options").json() == {"allow_register": False}
        with TestClient(app) as guest:
            blocked = guest.post("/api/auth/register", json={"email": "late@example.com", "password": "secret1"})
            assert blocked.status_code == 403
    finally:
        client.put("/api/settings", json={**current, "allow_register": True})


def test_login_is_rate_limited(client):
    register(client, "limited@example.com")
    client.post("/api/auth/logout")
    codes = [_login(client, "limited@example.com", "wrong-pass").status_code for _ in range(11)]
    assert codes[:10] == [400] * 10
    assert codes[10] == 429
    assert _login(client, "limited@example.com").status_code == 429


def test_initial_admin_must_change_password():
    from sqlalchemy import update

    import app.database as database
    from app.models import User

    db = database.SessionLocal()
    try:
        db.execute(update(User).where(User.email == "admin").values(must_change_password=True))
        db.commit()
    finally:
        db.close()
    try:
        with TestClient(app) as client:
            logged = _login(client, "admin", "admin")
            assert logged.status_code == 200
            assert logged.json()["must_change_password"] is True
            assert client.get("/api/auth/me").status_code == 200
            assert client.get("/api/items").status_code == 403
            assert client.get("/api/settings").status_code == 403
    finally:
        db = database.SessionLocal()
        try:
            db.execute(update(User).where(User.email == "admin").values(must_change_password=False))
            db.commit()
        finally:
            db.close()


def _offline_lcsc(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("app.routers.projects.fetch_lcsc", fail)


def test_lcsc_codes_are_uppercase_everywhere(client, monkeypatch):
    _offline_lcsc(monkeypatch)
    register(client, "upper@example.com")
    created = client.post("/api/items", json={"lcsc_code": " c25804 ", "mpn": "0603WAF1002T5E", "quantity": 1})
    assert created.status_code == 200, created.text
    assert created.json()["lcsc_code"] == "C25804"
    duplicate = client.post("/api/items", json={"lcsc_code": "C25804", "mpn": "DUP", "quantity": 1})
    assert duplicate.status_code == 400
    found = client.get("/api/items", params={"lcsc_code": "c258"})
    assert [row["id"] for row in found.json()["items"]] == [created.json()["id"]]
    updated = client.put(f"/api/items/{created.json()['id']}", json={**created.json(), "lcsc_code": "c25805"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["lcsc_code"] == "C25805"
    imported = client.post(
        "/api/projects/import",
        files={"file": ("quote.xlsx", _lower_code_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    line = imported.json()["lines"][0]
    assert line["lcsc_code"] == "C25805"
    added = client.post(f"/api/projects/{imported.json()['id']}/add-all")
    assert added.json() == {"added": 0, "incremented": 1}
    detail = client.get(f"/api/projects/{imported.json()['id']}").json()
    assert detail["lines"][0]["matched_item_id"] == created.json()["id"]


def _lower_code_workbook() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["商品编号", "Designator", "Quantity", "型号", "目录", "Footprint", "Name"])
    sheet.append(["c25805", "R1", 2, "0603WAF1002T5E", "电阻", "0603", "10kΩ"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_suggested_lines_are_not_checked_out(client, monkeypatch):
    _offline_lcsc(monkeypatch)
    register(client, "suggest@example.com")
    cap = client.post(
        "/api/items",
        json={"mpn": "LIB-CAP", "category": "电容", "footprint": "0402", "value": "100nF", "quantity": 10},
    )
    assert cap.status_code == 200, cap.text
    imported = client.post(
        "/api/projects/import",
        files={"file": ("quote.xlsx", _quote_workbook(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    project_id = imported.json()["id"]
    line = next(row for row in imported.json()["lines"] if row["category"] == "电容")
    _set_line(line["id"], "suggested", cap.json()["id"])

    single = client.post(f"/api/projects/{project_id}/lines/{line['id']}/checkout")
    assert single.status_code == 400
    bulk = client.post(f"/api/projects/{project_id}/checkout")
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["deducted"] == 0
    delta = client.post(f"/api/projects/{project_id}/lines/{line['id']}/stock-delta", json={"delta": -4})
    assert delta.status_code == 400
    assert client.get(f"/api/items/{cap.json()['id']}").json()["quantity"] == 10

    accepted = client.post(f"/api/projects/{project_id}/lines/{line['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    again = client.post(f"/api/projects/{project_id}/checkout")
    assert again.json()["deducted"] == 1
    assert client.get(f"/api/items/{cap.json()['id']}").json()["quantity"] == 6


def test_spec_categories_are_per_user(client):
    register(client, "spec-a@example.com")
    mine = client.get("/api/spec-categories")
    assert mine.status_code == 200, mine.text
    assert mine.json()
    added = client.post("/api/spec-categories", json={"name": "我的专属类目"})
    assert added.status_code == 200, added.text
    with TestClient(app) as other:
        register(other, "spec-b@example.com")
        theirs = other.get("/api/spec-categories")
        assert theirs.status_code == 200
        assert "我的专属类目" not in {row["name"] for row in theirs.json()}
        assert other.delete(f"/api/spec-categories/{added.json()['id']}").status_code == 404
    assert "我的专属类目" in {row["name"] for row in client.get("/api/spec-categories").json()}


def _item(client, **fields):
    response = client.post("/api/items", json={"quantity": 5, **fields})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _ids(client, **params):
    response = client.get("/api/items", params=params)
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()["items"]], response.json()


def test_smart_search_understands_value_and_package(client):
    register(client, "search@example.com")
    r0603 = _item(client, mpn="0603WAF1002T5E", category="电阻", footprint="R0603", value="10kΩ", params="精度: ±1%")
    r0402 = _item(client, mpn="0402WGF1002TCE", category="电阻", footprint="0402", value="10kΩ")
    r4k7 = _item(client, mpn="RC0603-4K7", category="电阻", footprint="0603", value="4.7kΩ")
    cap = _item(client, mpn="CL10B104KB8NNNC", category="电容", footprint="0603", value="100nF", params="耐压: 50V")
    ind = _item(client, mpn="SWPA4030S100MT", category="电感", footprint="SMD,4x4mm", value="10uH")

    found, page = _ids(client, q="10k 0603")
    assert found == [r0603]
    assert [hint["label"] for hint in page["hints"]] == ["电阻", "10kΩ", "封装 0603"]
    assert _ids(client, q="10K电阻0603")[0] == [r0603]
    assert sorted(_ids(client, q="10k")[0]) == sorted([r0603, r0402])
    assert _ids(client, q="4k7")[0] == [r4k7]
    assert _ids(client, q="0.1uF")[0] == [cap]
    assert _ids(client, q="100n 0603 50v")[0] == [cap]
    assert _ids(client, q="10uh")[0] == [ind]
    assert _ids(client, q="电容 0603")[0] == [cap]
    assert _ids(client, q="0603wAF")[0] == [r0603]

    empty, page = _ids(client, q="10k 1206")
    assert empty == [] and page["total"] == 0
    assert _ids(client, q="不存在的东西")[0] == []
    assert _ids(client, q="22uF")[0] == []
    with TestClient(app) as other:
        register(other, "search-other@example.com")
        assert _ids(other, q="10k 0603")[0] == []


def test_low_stock_flags_and_filter(client):
    register(client, "low@example.com")
    low = _item(client, mpn="LOW-1", quantity=3, min_stock=10)
    ok = _item(client, mpn="OK-1", quantity=30, min_stock=10)
    _item(client, mpn="NONE-1", quantity=0)
    rows, page = _ids(client)
    assert page["low_stock_count"] == 1
    flags = {row["id"]: row["low_stock"] for row in page["items"]}
    assert flags[low] is True and flags[ok] is False
    assert _ids(client, low_stock="true")[0] == [low]
    assert client.get("/api/map").json()["stats"]["low_stock_count"] == 1
    bad = client.post("/api/items", json={"mpn": "NEG", "quantity": 1, "min_stock": -1})
    assert bad.status_code == 422


def test_export_items_to_excel(client):
    register(client, "export@example.com")
    _item(client, lcsc_code="c1001", mpn="=HYPERLINK(1)", category="电阻", footprint="0603", value="1kΩ", min_stock=9)
    _item(client, mpn="OTHER", category="电容", value="1uF")
    response = client.get("/api/items/export", params={"category": "电阻"})
    assert response.status_code == 200, response.text
    assert "spreadsheetml" in response.headers["content-type"]
    assert ".xlsx" in response.headers["content-disposition"]
    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][0] == "立创编号"
    assert len(rows) == 2
    assert rows[1][0] == "C1001"
    assert rows[1][1] == "'=HYPERLINK(1)"
    assert rows[1][11] == "是"
    with TestClient(app) as other:
        register(other, "export-other@example.com")
        theirs = openpyxl.load_workbook(io.BytesIO(other.get("/api/items/export").content)).active
        assert theirs.max_row == 1


def test_admin_backup_zip(client):
    register(client, "backup-user@example.com")
    assert client.get("/api/settings/backup").status_code == 403
    _admin(client)
    response = client.get("/api/settings/backup")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert "database/_test.sqlite" in names
    assert not any("secret_key" in name for name in names)
    assert archive.read("database/_test.sqlite").startswith(b"SQLite format 3")
