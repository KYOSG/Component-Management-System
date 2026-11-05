import random
import threading
from collections import deque

from sqlalchemy import create_engine

from app.bootstrap import ensure_item_sync_columns
from app.services.lcsc import LcscError
from app.services.lcsc_refresh import RequestPacer, perform_refresh


def register(client, email):
    response = client.post("/api/auth/register", json={"email": email, "password": "secret1"})
    assert response.status_code == 200, response.text
    return client


def create_item(client, **extra):
    body = {"mpn": "OLD", "name": "旧名称", "quantity": 4, "remark": "保留", "min_stock": 2}
    body.update(extra)
    response = client.post("/api/items", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_pacer_keeps_one_request_and_random_gap():
    pacer = RequestPacer(gap_min=0, gap_max=0, rng=random.Random(0))
    assert pacer.acquire(max_wait=0)
    assert pacer.acquire(max_wait=0) is False
    pacer.release()
    assert pacer.acquire(max_wait=0)
    pacer.release()

    clock = {"now": 100.0}

    def now():
        return clock["now"]

    paced = RequestPacer(rng=random.Random(1), clock=now)
    gaps = []
    for _ in range(6):
        paced.in_flight = True
        paced.release()
        gaps.append(paced.ready_at - clock["now"])
    assert min(gaps) >= 2
    assert max(gaps) <= 3.6
    assert max(gaps) - min(gaps) > 0.2

    stop = threading.Event()
    stop.set()
    assert RequestPacer().acquire(stop=stop) is False


def test_schedule_never_exceeds_thirty_per_minute():
    clock = {"now": 0.0}

    def now():
        return clock["now"]

    pacer = RequestPacer(rng=random.Random(2), clock=now)
    stamps = []
    for _ in range(80):
        while True:
            delay = pacer.seconds_until(clock["now"])
            if delay <= 0 and not pacer.in_flight:
                break
            clock["now"] += delay if delay > 0 else 0.2
        pacer.in_flight = True
        pacer.starts.append(clock["now"])
        stamps.append(clock["now"])
        clock["now"] += 0.2
        pacer.release()
    for index, stamp in enumerate(stamps):
        count = sum(1 for earlier in stamps[: index + 1] if stamp - earlier < 60)
        assert count <= 30
    gaps = [right - left for left, right in zip(stamps, stamps[1:])]
    assert min(gaps) >= 2.2 - 1e-9
    assert max(gaps) - min(gaps) > 0.2
    assert isinstance(pacer.starts, deque)


def test_selected_refresh_blocks_edit_and_query_until_finished(client, monkeypatch):
    register(client, "refresh@example.com")
    item = create_item(client, lcsc_code="C100", unit_price=0.02, value="1kΩ")
    blank = create_item(client, mpn="NOCODE", quantity=1)
    queued = client.post("/api/items/lcsc-refresh", json={"item_ids": [item["id"], blank["id"]]})
    assert queued.status_code == 200, queued.text
    assert queued.json()["queued"] == 1
    assert queued.json()["skipped_no_code"] == 1

    again = client.post("/api/items/lcsc-refresh", json={"item_ids": [item["id"]]})
    assert again.json()["queued"] == 0
    assert again.json()["skipped_busy"] == 1
    assert client.get("/api/items/lcsc-refresh/status").json()["queued"] == 1

    denied = client.put(
        f"/api/items/{item['id']}",
        json={"lcsc_code": "C100", "name": "想改", "quantity": 4, "remark": "保留"},
    )
    assert denied.status_code == 409
    assert "不能查询或编辑" in denied.json()["detail"]
    assert client.get("/api/lcsc/C100", params={"item_id": item["id"]}).status_code == 409
    assert client.get("/api/lcsc/c100").status_code == 409

    def fake_fetch(code, catalog, user_id=None):
        assert code == "C100"
        return {
            "lcsc_code": "C100",
            "mpn": "RC0603FR",
            "name": "厚膜电阻",
            "brand": "YAGEO",
            "footprint": "0603",
            "category": "电阻",
            "value": "10kΩ",
            "params": "精度: ±1%",
            "specs": {"tolerance": "±1%", "power": "100mW"},
            "datasheet_url": "https://example.com/c100.pdf",
            "image_url": "",
            "unit_price": 1.23,
        }

    monkeypatch.setattr("app.services.lcsc_refresh.fetch_lcsc", fake_fetch)
    perform_refresh(item["id"])
    stored = client.get(f"/api/items/{item['id']}").json()
    assert stored["mpn"] == "RC0603FR"
    assert stored["name"] == "厚膜电阻"
    assert stored["brand"] == "YAGEO"
    assert stored["footprint"] == "0603"
    assert stored["category"] == "电阻"
    assert stored["value"] == "10kΩ"
    assert stored["specs"]["tolerance"] == "±1%"
    assert stored["datasheet_url"] == "https://example.com/c100.pdf"
    assert stored["quantity"] == 4
    assert stored["min_stock"] == 2
    assert stored["remark"] == "保留"
    assert stored["unit_price"] == 0.02
    assert stored["lcsc_sync_status"] == "idle"

    missing_price = create_item(client, lcsc_code="C101", quantity=3)
    assert missing_price["unit_price"] is None
    client.post("/api/items/lcsc-refresh", json={"item_ids": [missing_price["id"]]})

    def fake_other(code, catalog, user_id=None):
        payload = fake_fetch("C100", catalog, user_id=user_id)
        payload["lcsc_code"] = code
        return payload

    monkeypatch.setattr("app.services.lcsc_refresh.fetch_lcsc", fake_other)
    perform_refresh(missing_price["id"])
    filled = client.get(f"/api/items/{missing_price['id']}").json()
    assert filled["unit_price"] == 1.23
    assert filled["quantity"] == 3

    allowed = client.put(
        f"/api/items/{item['id']}",
        json={"lcsc_code": "C100", "name": "手改", "quantity": 4, "remark": "保留", "unit_price": 0.02},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["name"] == "手改"


def test_failed_refresh_can_be_edited_and_retried(client, monkeypatch):
    register(client, "fail@example.com")
    item = create_item(client, lcsc_code="C300", name="原名")

    def explode(code, catalog, user_id=None):
        raise LcscError("查询失败，请手填")

    monkeypatch.setattr("app.services.lcsc_refresh.fetch_lcsc", explode)
    assert client.post("/api/items/lcsc-refresh", json={"all": True}).json()["queued"] == 1
    perform_refresh(item["id"])
    failed = client.get(f"/api/items/{item['id']}").json()
    assert failed["lcsc_sync_status"] == "failed"
    assert failed["name"] == "原名"
    assert "稍后重试" in failed["lcsc_sync_error"]
    edited = client.put(f"/api/items/{item['id']}", json={"lcsc_code": "C300", "name": "手改", "quantity": 4})
    assert edited.status_code == 200, edited.text
    assert edited.json()["lcsc_sync_status"] == "idle"
    assert client.get("/api/items/lcsc-refresh/status").json()["failed"] == 0


def test_order_commit_queues_codes_that_were_not_in_stock_yet(client):
    register(client, "order@example.com")
    create_item(client, lcsc_code="C100", quantity=5)
    preview = client.post("/api/items/lcsc-refresh", json={"lcsc_codes": ["c100", "C200"]})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["queued"] == 1
    assert body["queued_codes"] == ["C100"]
    assert body["pending_codes"] == ["C200"]

    committed = client.post(
        "/api/items/order-commit",
        json={
            "order_no": "SO-REFRESH",
            "refresh_codes": ["C200"],
            "lines": [
                {
                    "lcsc_code": "C200",
                    "mpn": "订单型号",
                    "name": "厚膜电阻 10kΩ",
                    "brand": "订单品牌",
                    "footprint": "0603",
                    "ship_qty": 8,
                    "unit_price": 0.01,
                    "skip": False,
                }
            ],
        },
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["refresh_queued"] == 1
    rows = client.get("/api/items", params={"lcsc_code": "C200"}).json()["items"]
    assert len(rows) == 1
    assert rows[0]["quantity"] == 8
    assert rows[0]["unit_price"] == 0.01
    assert rows[0]["lcsc_sync_status"] == "queued"
    assert rows[0]["mpn"] == "订单型号"


def test_library_refresh_ignores_other_users(client):
    register(client, "owner@example.com")
    create_item(client, lcsc_code="C1")
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    create_item(client, lcsc_code="C2")
    queued = client.post("/api/items/lcsc-refresh", json={"all": True})
    assert queued.json()["queued"] == 1
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret1"})
    own = client.get("/api/items", params={"lcsc_code": "C1"}).json()["items"]
    assert own[0]["lcsc_sync_status"] == "idle"


def test_old_items_table_gains_sync_columns(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "old.sqlite").as_posix())
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE items (id INTEGER PRIMARY KEY, lcsc_code VARCHAR(64))")
    ensure_item_sync_columns(engine)
    ensure_item_sync_columns(engine)
    with engine.connect() as connection:
        names = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(items)")]
    assert names.count("lcsc_sync_status") == 1
    assert "lcsc_sync_error" in names
    assert "lcsc_sync_at" in names


def test_refresh_request_needs_one_target(client):
    register(client, "empty@example.com")
    response = client.post("/api/items/lcsc-refresh", json={})
    assert response.status_code == 422
