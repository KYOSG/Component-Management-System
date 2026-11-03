import io
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.order_import import OrderError, parse_order
from app.services.specs import default_catalog
from tests.samples import QUOTE_FILE
from tests.test_api import register

ORDER_FILE = Path(__file__).resolve().parents[2] / "temp" / "立创商城订单详情-SO26102826926.xls"
HEADERS = ["序号", "商品编号", "品牌", "厂家型号", "封装", "商品名称", "订购数量（修改后）", "发货数量", "是否不发此货", "商品单价"]


def _line(number, code, name, ship, ordered=None, withhold="", price="￥0.010000/个", mpn="RC0603FR-0710KL"):
    bought = ship if ordered is None else ordered
    return [number, code, "YAGEO(国巨)", mpn, "0603", name, f"{bought}个", f"{ship}个", withhold, price]


def _workbook(rows, *, order_no="SO100", ordered_at="2026-10-28 17:21", data_on_second=False):
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "template"
    if data_on_second:
        first.append(HEADERS)
        sheet = workbook.create_sheet("订单")
    else:
        sheet = first
        decoy = workbook.create_sheet("template-empty")
        decoy.append(HEADERS)
    sheet.append(["订单编号：", order_no])
    sheet.append(["下单日期：", ordered_at])
    sheet.append(["商品明细列表"])
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _parsed(data, filename="订单-SO100.xlsx"):
    return parse_order(filename, data, default_catalog())


def test_real_lcsc_order_uses_shipped_quantity():
    if not ORDER_FILE.is_file():
        pytest.skip("缺少立创订单样例")
    parsed = parse_order(ORDER_FILE.name, ORDER_FILE.read_bytes(), default_catalog())
    assert parsed.order_no == "SO26102826926"
    assert parsed.ordered_at == "2026-10-28 17:21"
    assert len(parsed.lines) == 44
    assert sum(line.ship_qty for line in parsed.lines if not line.skip) == 1770
    assert all(not line.skip for line in parsed.lines)

    by_code = {line.lcsc_code: line for line in parsed.lines}
    resistor = by_code["C2906982"]
    assert resistor.mpn == "FRC0603F1002TS"
    assert resistor.footprint == "0603"
    assert resistor.ship_qty == 100
    assert resistor.ordered_qty == 100
    assert resistor.category == "电阻"
    assert resistor.value == "10kΩ"
    assert resistor.unit_price == 0.01273
    assert resistor.specs["tolerance"] == "±1%"
    assert resistor.specs["power"] == "100mW"
    assert "阻值：10kΩ" in resistor.params

    zero = by_code["C21189"]
    assert zero.value == "0Ω"
    assert zero.category == "电阻"
    assert zero.ship_qty == 100

    capacitor = by_code["C7432769"]
    assert capacitor.value == "2.2μF"
    assert capacitor.category == "电容"
    assert capacitor.specs["voltage"] == "50V"
    assert capacitor.specs["tolerance"] == "±10%"
    assert capacitor.ship_qty == 20

    assert by_code["C107083"].value == "220nF"
    assert by_code["C46550415"].value == "100μF"
    assert by_code["C167221"].value == "6.8μH"
    assert by_code["C167221"].category == "电感"

    crystal = by_code["C341525"]
    assert crystal.value == "8MHz"
    assert crystal.category == ""
    assert crystal.ship_qty == 5

    bead = by_code["C85827"]
    assert bead.value == "220Ω"
    assert bead.category == ""

    common = by_code["C54888"]
    assert common.value == "90Ω"
    assert common.category == ""

    assert by_code["C75882"].category == "MOS"
    assert by_code["C84263"].category == "二极管"
    mcu = by_code["C8304"]
    assert mcu.mpn == "STM32F103CBT6"
    assert mcu.ship_qty == 3
    assert mcu.unit_price == 15.16
    assert mcu.value == ""

    first = by_code["C47501220"]
    assert first.brand.startswith("FUXINSEMI")
    assert first.footprint == "SOD-123FL"
    assert first.ship_qty == 50
    assert first.unit_price == 0.0688


def test_order_on_later_sheet_skips_withheld_and_zero_ship():
    resistor = "厚膜电阻 10kΩ ±1% 100mW 编带"
    data = _workbook(
        [
            _line(1, "C200", resistor, 15, price="￥0.030000/个"),
            _line(2, "C300", "厚膜电阻 1kΩ ±1% 100mW 编带", 9, withhold="是"),
            _line(3, "C400", "厚膜电阻 2kΩ ±1% 100mW 编带", 0, ordered=10),
            _line(4, "C500", "厚膜电阻 4.7kΩ ±1% 100mW 编带", 4),
            _line(5, "C500", "厚膜电阻 4.7kΩ ±1% 100mW 编带", 6),
            _line(6, "C341", "8MHz ±0.07% 内置负载电容:33pF 编带", 2, mpn="CSTNE8M00"),
            _line(7, "C858", "单路 0603磁珠 阻抗220Ω@100MHz 编带", 3, mpn="BLM18"),
        ],
        order_no="",
        data_on_second=True,
    )
    parsed = _parsed(data, "立创商城订单详情-SO999.xlsx")
    assert parsed.order_no == "SO999"
    by_code = {}
    for line in parsed.lines:
        by_code.setdefault(line.lcsc_code, []).append(line)
    assert by_code["C300"][0].skip is True
    assert by_code["C300"][0].skip_reason == "不发此货"
    assert by_code["C400"][0].skip is True
    assert by_code["C400"][0].ship_qty == 0
    assert by_code["C341"][0].value == "8MHz"
    assert by_code["C341"][0].category == ""
    assert by_code["C858"][0].value == "220Ω"
    assert by_code["C858"][0].category == ""
    assert by_code["C200"][0].value == "10kΩ"
    assert [line.ship_qty for line in by_code["C500"]] == [4, 6]


def test_quote_workbook_is_not_an_order():
    try:
        parse_order(QUOTE_FILE.name, QUOTE_FILE.read_bytes(), default_catalog())
        raise AssertionError("报价单不应该被当成订单详情")
    except OrderError as exc:
        assert "无法识别" in str(exc)


def _commit_body(preview):
    return {
        "order_no": preview["order_no"],
        "lines": [
            {
                "lcsc_code": row["lcsc_code"],
                "mpn": row["mpn"],
                "name": row["name"],
                "brand": row["brand"],
                "footprint": row["footprint"],
                "ship_qty": row["ship_qty"],
                "unit_price": row["unit_price"],
                "skip": row["skip"],
            }
            for row in preview["lines"]
        ],
    }


def _find(client, code):
    response = client.get("/api/items", params={"lcsc_code": code, "page_size": 50})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_preview_then_commit_creates_and_increments(client):
    register(client, "order-in@example.com")
    existing = client.post(
        "/api/items",
        json={
            "lcsc_code": "C100",
            "mpn": "OLD-MPN",
            "name": "旧物料",
            "brand": "OLD",
            "footprint": "0402",
            "category": "电阻",
            "value": "1kΩ",
            "quantity": 5,
            "unit_price": 1.5,
        },
    )
    assert existing.status_code == 200, existing.text
    resistor = "厚膜电阻 10kΩ ±1% 100mW 编带"
    raw = _workbook(
        [
            _line(1, "C100", resistor, 40, price="￥0.020000/个", mpn="NEW-MPN"),
            _line(2, "C200", resistor, 15, price="￥0.030000/个"),
            _line(3, "C300", "厚膜电阻 1kΩ ±1% 100mW 编带", 9, withhold="是"),
            _line(4, "C400", "厚膜电阻 2kΩ ±1% 100mW 编带", 0, ordered=8),
            _line(5, "C500", "厚膜电阻 4.7kΩ ±1% 100mW 编带", 4),
            _line(6, "C500", "厚膜电阻 4.7kΩ ±1% 100mW 编带", 6),
        ]
    )
    files = {"file": ("订单.xlsx", raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    preview = client.post("/api/items/order-preview", files=files)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["order_no"] == "SO100"
    assert body["already_imported"] is False
    assert body["create_count"] == 2
    assert body["stock_count"] == 2
    assert body["skip_count"] == 2
    assert body["ship_total"] == 65
    actions = {row["lcsc_code"]: row for row in body["lines"] if row["lcsc_code"] != "C500"}
    assert actions["C100"]["action"] == "stock"
    assert actions["C100"]["current_quantity"] == 5
    assert actions["C200"]["action"] == "create"
    assert actions["C300"]["action"] == "skip"
    assert actions["C400"]["action"] == "skip"
    duplicate = [row for row in body["lines"] if row["lcsc_code"] == "C500"]
    assert [row["action"] for row in duplicate] == ["create", "stock"]
    assert duplicate[1]["current_quantity"] == 4

    empty = client.post("/api/items/order-commit", json={"order_no": "SO100", "lines": []})
    assert empty.status_code == 400

    committed = client.post("/api/items/order-commit", json=_commit_body(body))
    assert committed.status_code == 200, committed.text
    assert committed.json() == {"created": 2, "stocked": 2, "skipped": 2, "ship_total": 65}

    kept = _find(client, "C100")
    assert len(kept) == 1
    assert kept[0]["quantity"] == 45
    assert kept[0]["mpn"] == "OLD-MPN"
    assert kept[0]["unit_price"] == 1.5
    assert kept[0]["value"] == "1kΩ"

    created = _find(client, "C200")
    assert len(created) == 1
    assert created[0]["quantity"] == 15
    assert created[0]["unit_price"] == 0.03
    assert created[0]["category"] == "电阻"
    assert created[0]["value"] == "10kΩ"
    assert created[0]["footprint"] == "0603"
    assert created[0]["specs"]["tolerance"] == "±1%"
    assert created[0]["specs"]["power"] == "100mW"
    assert created[0]["locations"][0]["location_type"] == "unboxed"
    assert created[0]["locations"][0]["quantity"] == 15

    assert _find(client, "C300") == []
    assert _find(client, "C400") == []
    merged = _find(client, "C500")
    assert len(merged) == 1
    assert merged[0]["quantity"] == 10
    assert merged[0]["value"] == "4.7kΩ"

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import StockEvent

    db = SessionLocal()
    try:
        notes = db.scalars(select(StockEvent.note).where(StockEvent.item_id == created[0]["id"])).all()
    finally:
        db.close()
    assert notes == ["订单入库 SO100"]

    again = client.post("/api/items/order-preview", files=files)
    assert again.status_code == 200, again.text
    assert again.json()["already_imported"] is True
    assert again.json()["stock_count"] == 4
    assert again.json()["create_count"] == 0

    with TestClient(app) as other:
        register(other, "order-other@example.com")
        foreign = other.post("/api/items/order-preview", files=files)
        assert foreign.status_code == 200, foreign.text
        assert foreign.json()["already_imported"] is False
        assert foreign.json()["create_count"] == 3
        assert foreign.json()["stock_count"] == 1
        assert _find(other, "C100") == []
        assert _find(client, "C100")[0]["quantity"] == 45


def test_unknown_workbook_is_rejected(client):
    register(client, "order-bad@example.com")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["名称", "数量"])
    sheet.append(["电阻", 1])
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = client.post(
        "/api/items/order-preview",
        files={"file": ("notes.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 400
    assert "无法识别" in response.json()["detail"]
    quoted = client.post(
        "/api/items/order-preview",
        files={"file": (QUOTE_FILE.name, QUOTE_FILE.read_bytes(), "application/vnd.ms-excel")},
    )
    assert quoted.status_code == 400
    assert "无法识别" in quoted.json()["detail"]
