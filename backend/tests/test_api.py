import io

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from tests.samples import EDA_FILE, QUOTE_FILE


def register(client, email):
    response = client.post("/api/auth/register", json={"email": email, "password": "secret1"})
    assert response.status_code == 200, response.text
    return client


def test_register_login_and_isolation(client):
    register(client, "a@example.com")
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    login = client.post("/api/auth/login", json={"email": "a@example.com", "password": "secret1"})
    assert login.status_code == 200
    assert client.get("/api/items").status_code == 200


def test_boxes_are_independent_and_items_move(client):
    register(client, "box@example.com")
    wide = client.post("/api/boxes", json={"name": "宽盒", "rows": 5, "cols": 10, "remark": ""})
    small = client.post("/api/boxes", json={"name": "小盒", "rows": 3, "cols": 4, "remark": ""})
    assert wide.status_code == 200
    assert small.status_code == 200
    wide_id = wide.json()["id"]
    small_id = small.json()["id"]
    created = client.post(
        "/api/items",
        json={
            "mpn": "R1",
            "name": "电阻",
            "footprint": "0603",
            "category": "电阻",
            "value": "10kΩ",
            "quantity": 8,
            "box_id": wide_id,
            "row": 2,
            "col": 3,
        },
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]
    conflict = client.post(
        "/api/items",
        json={"mpn": "R2", "quantity": 1, "box_id": wide_id, "row": 2, "col": 3},
    )
    assert conflict.status_code == 400
    shrink = client.put("/api/boxes/" + str(wide_id), json={"name": "宽盒", "rows": 1, "cols": 1, "remark": ""})
    assert shrink.status_code == 400
    assert "移走" in shrink.json()["detail"]
    moved = client.post(f"/api/items/{item_id}/unbox")
    assert moved.json()["box_id"] is None
    placed = client.put(
        f"/api/items/{item_id}",
        json={**created.json(), "box_id": small_id, "row": 1, "col": 1, "quantity": 8},
    )
    assert placed.status_code == 200
    inventory = client.get("/api/map").json()
    sizes = {box["name"]: (box["rows"], box["cols"], len(box["cells"])) for box in inventory["boxes"]}
    assert sizes["宽盒"] == (5, 10, 50)
    assert sizes["小盒"] == (3, 4, 12)
    assert inventory["stats"]["item_count"] == 1
    deleted = client.delete(f"/api/boxes/{small_id}")
    assert deleted.status_code == 200
    again = client.get("/api/map").json()
    assert again["unboxed"][0]["mpn"] == "R1"
    assert again["unboxed"][0]["box_id"] is None


def test_import_samples_match_exact_and_substitute(client):
    register(client, "bom@example.com")
    box = client.post("/api/boxes", json={"name": "电阻盒", "rows": 5, "cols": 10}).json()
    library = client.post(
        "/api/items",
        json={
            "mpn": "LOCAL-10K",
            "footprint": "0603",
            "category": "电阻",
            "value": "10kΩ",
            "quantity": 100,
            "box_id": box["id"],
            "row": 1,
            "col": 1,
        },
    )
    assert library.status_code == 200
    eda = client.post(
        "/api/projects/import",
        files={"file": (EDA_FILE.name, EDA_FILE.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert eda.status_code == 200, eda.text
    body = eda.json()
    assert body["format"] == "easyeda_v131"
    assert body["line_count"] == 45
    assert body["ai_enabled"] is False
    target = next(line for line in body["lines"] if line["mpn"] == "0603WAF1002T5E")
    assert target["lcsc_code"] == ""
    assert target["footprint"] == "R0603"
    assert target["match_status"] == ""
    assert target["reason"] == ""
    assert target["locations"] == []
    coded = client.post(
        "/api/items",
        json={"lcsc_code": "C105580", "mpn": "RC0603FR-075K1L", "footprint": "0603", "quantity": 500},
    )
    assert coded.status_code == 200
    quote = client.post(
        "/api/projects/import",
        files={"file": (QUOTE_FILE.name, QUOTE_FILE.read_bytes(), "application/vnd.ms-excel")},
    )
    assert quote.status_code == 200, quote.text
    quote_body = quote.json()
    assert quote_body["purchase_sets"] == 2
    assert quote_body["order_no"] == "BOM261020000440"
    matched = next(line for line in quote_body["lines"] if line["lcsc_code"] == "C105580")
    assert matched["designators"] == "R13,R14"
    assert matched["quantity_per_board"] == 2
    assert matched["quantity_required"] == 4
    assert matched["match_status"] == ""
    assert matched["reason"] == ""
    highlighted = client.get("/api/map", params={"project_id": quote_body["id"]}).json()
    assert highlighted["highlights"] == {}
    with TestClient(app) as other:
        register(other, "other@example.com")
        assert other.get("/api/projects").json() == []
        assert other.get(f"/api/projects/{quote_body['id']}").status_code == 404


def test_purchase_sets_recalculate_required(client):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import ProjectLine

    register(client, "sets@example.com")
    imported = client.post(
        "/api/projects/import",
        files={"file": (QUOTE_FILE.name, QUOTE_FILE.read_bytes(), "application/vnd.ms-excel")},
    )
    assert imported.status_code == 200, imported.text
    project_id = imported.json()["id"]
    db = SessionLocal()
    try:
        stored = db.scalar(select(ProjectLine).where(ProjectLine.project_id == project_id, ProjectLine.lcsc_code == "C105580"))
        stored.quantity_required = 100
        db.commit()
    finally:
        db.close()
    rematched = client.post(f"/api/projects/{project_id}/match")
    assert rematched.status_code == 200, rematched.text
    line = next(item for item in rematched.json()["lines"] if item["lcsc_code"] == "C105580")
    assert line["quantity_per_board"] == 2
    assert line["quantity_required"] == 4
    updated = client.put(f"/api/projects/{project_id}", json={"purchase_sets": 3})
    assert updated.status_code == 200, updated.text
    assert updated.json()["purchase_sets"] == 3
    changed = next(item for item in updated.json()["lines"] if item["lcsc_code"] == "C105580")
    assert changed["quantity_required"] == 6
    rejected = client.put(f"/api/projects/{project_id}", json={"purchase_sets": 0})
    assert rejected.status_code == 422
    with TestClient(app) as other:
        register(other, "sets-other@example.com")
        assert other.put(f"/api/projects/{project_id}", json={"purchase_sets": 4}).status_code == 404


def test_initial_admin_and_user_removal(client):
    from sqlalchemy import func, select

    from app.bootstrap import prepare_database
    from app.database import SessionLocal
    from app.models import Box, Item, Project, User

    admin = client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    assert admin.status_code == 200, admin.text
    assert admin.json()["is_admin"] is True
    admin_id = admin.json()["id"]
    assert client.put(
        f"/api/users/{admin_id}",
        json={"email": "admin", "password": "", "is_admin": False},
    ).status_code == 400
    assert client.delete(f"/api/users/{admin_id}").status_code == 400

    created = client.post("/api/users", json={"email": "staff@example.com", "password": "secret1", "is_admin": False})
    assert created.status_code == 200, created.text
    staff_id = created.json()["id"]

    client.post("/api/auth/login", json={"email": "staff@example.com", "password": "secret1"})
    assert client.get("/api/auth/me").json()["is_admin"] is False
    assert client.get("/api/users").status_code == 403
    box = client.post("/api/boxes", json={"name": "员工盒", "rows": 2, "cols": 2, "remark": ""})
    assert box.status_code == 200, box.text
    item = client.post(
        "/api/items",
        json={"mpn": "R9", "quantity": 3, "box_id": box.json()["id"], "row": 1, "col": 1},
    )
    assert item.status_code == 200, item.text
    imported = client.post(
        "/api/projects/import",
        files={"file": (EDA_FILE.name, EDA_FILE.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text

    db = SessionLocal()
    try:
        assert db.get(Item, item.json()["id"]).user_id == staff_id
        assert db.get(Box, box.json()["id"]).user_id == staff_id
        assert db.get(Project, imported.json()["id"]).user_id == staff_id
    finally:
        db.close()

    client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    removed = client.delete(f"/api/users/{staff_id}")
    assert removed.status_code == 200, removed.text
    db = SessionLocal()
    try:
        assert db.get(User, staff_id) is None
        assert db.scalar(select(func.count()).select_from(Item).where(Item.user_id == staff_id)) == 0
        assert db.scalar(select(func.count()).select_from(Box).where(Box.user_id == staff_id)) == 0
        assert db.scalar(select(func.count()).select_from(Project).where(Project.user_id == staff_id)) == 0
        prepare_database()
        assert db.scalar(select(func.count()).select_from(User).where(User.email == "admin")) == 1
    finally:
        db.close()
    assert client.post("/api/auth/login", json={"email": "staff@example.com", "password": "secret1"}).status_code == 400


def test_admin_can_update_account(client):
    client.post("/api/auth/login", json={"email": "admin", "password": "admin"})
    created = client.post("/api/users", json={"email": "edit@example.com", "password": "secret1", "is_admin": False})
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]
    updated = client.put(
        f"/api/users/{user_id}",
        json={"email": "edited@example.com", "password": "secret2", "is_admin": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["email"] == "edited@example.com"
    listed = client.get("/api/users")
    assert any(row["email"] == "edited@example.com" for row in listed.json())
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "edited@example.com", "password": "secret2"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "edit@example.com", "password": "secret1"}).status_code == 400


def test_unknown_file_does_not_create_project(client):
    register(client, "badfile@example.com")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["foo", "bar"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = client.post(
        "/api/projects/import",
        files={"file": ("bad.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert "无法识别" in response.json()["detail"]
    assert client.get("/api/projects").json() == []
