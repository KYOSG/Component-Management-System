from app.services.bom import parse_upload
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
