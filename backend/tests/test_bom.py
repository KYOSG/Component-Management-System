from app.services.bom import ParsedLine, parse_upload
from tests.samples import EDA_FILE, QUOTE_FILE


def test_easyeda_sample_imports_real_rows():
    parsed = parse_upload(EDA_FILE.name, EDA_FILE.read_bytes())
    assert parsed.format == "easyeda_v131"
    assert parsed.purchase_sets == 1
    assert len(parsed.lines) == 45
    first = parsed.lines[0]
    assert first.mpn == "CL10A105KB8NNNC"
    assert first.footprint == "C0603"
    assert first.value == "1uF"
    assert first.brand.startswith("SAMSUNG")
    assert first.lcsc_code == ""
    assert first.quantity_per_board == 1
    assert "Tolerance" in first.params
    assert "±10%" in first.params
    last = parsed.lines[-1]
    assert last.line_no == 45
    assert last.mpn == "0603WAF1002T5E"
    assert last.footprint == "R0603"
    assert last.value == "10kΩ"
    assert last.quantity_required == 21


def test_lcsc_quote_sample():
    parsed = parse_upload(QUOTE_FILE.name, QUOTE_FILE.read_bytes())
    assert parsed.format == "lcsc_quote"
    assert "树莓派" in parsed.name
    assert parsed.purchase_sets == 2
    assert parsed.order_no == "BOM261020000440"
    assert len(parsed.lines) == 9
    line = next(item for item in parsed.lines if item.lcsc_code == "C105580")
    assert line.designators == "R13,R14"
    assert line.quantity_per_board == 2
    assert line.quantity_required == 4
    assert line.mpn == "RC0603FR-075K1L"
    assert line.brand.startswith("YAGEO")
    assert line.footprint == "0603"
    assert line.value == "5.1kΩ"
    assert line.category == "电阻"


def test_location_omits_part_number():
    from app.routers.projects import _location

    assert _location({"mpn": "0603WAF6201T5E", "box_name": "料盒1", "row": 1, "col": 1, "quantity": 100}) == "料盒1 1-1（库存 100）"
    assert _location({"mpn": "RC0603FR-075K1L", "quantity": 0}) == "未入盒（库存 0）"


def test_easyeda_supplier_part_is_lcsc_code():
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["No.", "Quantity", "Footprint", "LCSC Price", "Manufacturer", "Manufacturer Part", "Supplier Part", "Value"])
    sheet.append([1, 2, "R0603", "", "YAGEO", "RC0603FR-0710KL", "C17414", "10kΩ"])
    sheet.append([2, 1, "C0603", "", "SAMSUNG", "CL10A105KB8NNNC", "", "1uF"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    parsed = parse_upload("board.xlsx", buffer.getvalue())
    assert parsed.format == "easyeda_v131"
    coded, plain = parsed.lines
    assert coded.lcsc_code == "C17414"
    assert coded.needs_lcsc_enrich is True
    assert coded.mpn == "RC0603FR-0710KL"
    assert "Supplier Part" not in coded.params
    assert plain.lcsc_code == ""
    assert plain.needs_lcsc_enrich is False


def test_enrich_uses_lcsc_fields_and_keeps_original_on_failure(monkeypatch):
    from app.routers.projects import _enrich_lines

    def fake_fetch(code):
        if code == "C-FAIL":
            raise RuntimeError("offline")
        return {
            "mpn": "FROM-API",
            "brand": "YAGEO",
            "footprint": "0603",
            "value": "10kΩ",
            "params": "阻值: 10kΩ",
            "name": "10k 电阻",
            "category": "电阻",
        }

    monkeypatch.setattr("app.routers.projects.fetch_lcsc", fake_fetch)
    filled = ParsedLine(line_no=1, lcsc_code="C17414", mpn="OLD", value="10k", needs_lcsc_enrich=True)
    failed = ParsedLine(line_no=2, lcsc_code="C-FAIL", mpn="KEEP", needs_lcsc_enrich=True)
    skipped = ParsedLine(line_no=3, lcsc_code="C999", mpn="SKIP", needs_lcsc_enrich=False)
    _enrich_lines([filled, failed, skipped])
    assert filled.mpn == "FROM-API"
    assert filled.category == "电阻"
    assert filled.product_name == "10k 电阻"
    assert filled.params == "阻值: 10kΩ"
    assert failed.mpn == "KEEP"
    assert skipped.mpn == "SKIP"


def test_unknown_workbook_is_rejected():
    import io

    import openpyxl

    from app.services.bom import BomError, parse_upload

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["名称", "数量"])
    sheet.append(["电阻", 1])
    buffer = io.BytesIO()
    workbook.save(buffer)
    try:
        parse_upload("notes.xlsx", buffer.getvalue())
        raise AssertionError("应该拒绝无法识别的文件")
    except BomError as exc:
        assert "无法识别" in str(exc)
