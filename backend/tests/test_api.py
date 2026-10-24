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
    assert target["match_status"] == "suggested"
    assert "0603" in target["reason"]
    assert "10kΩ" in target["reason"]
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
    assert matched["quantity_required"] == 100
    assert matched["match_status"] == "matched"
    highlighted = client.get("/api/map", params={"project_id": quote_body["id"]}).json()
    assert "R13" in highlighted["highlights"][str(coded.json()["id"])]
    with TestClient(app) as other:
        register(other, "other@example.com")
        assert other.get("/api/projects").json() == []
        assert other.get(f"/api/projects/{quote_body['id']}").status_code == 404


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
