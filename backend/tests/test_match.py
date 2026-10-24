from app.services.match import ItemSnap, LineSnap, footprint_main, match_lines, norm_value


def item(**kwargs) -> ItemSnap:
    defaults = dict(id=1, quantity=100, footprint="0603", category="电阻", value="10kΩ", mpn="LIB-1")
    defaults.update(kwargs)
    return ItemSnap(**defaults)


def line(**kwargs) -> LineSnap:
    defaults = dict(id=1, quantity_required=10, footprint="R0603", value="10kΩ", mpn="BOM-1")
    defaults.update(kwargs)
    return LineSnap(**defaults)


def test_footprint_and_value_normalization():
    assert footprint_main("R0603") == "0603"
    assert footprint_main("C0603") == "0603"
    assert footprint_main("SOT-23-3_L2.9-W1.3") == "SOT-23"
    assert footprint_main("SOT-223-4_L6.5") == "SOT-223"
    assert norm_value("5.1kΩ") == norm_value("5.1k")
    assert norm_value("4.7μF") == norm_value("4.7uF")


def test_exact_code_matches_without_deepseek():
    result = match_lines(
        [line(lcsc_code="C105580", mpn="OTHER")],
        [item(lcsc_code="C105580", mpn="RC0603FR-075K1L", quantity=50)],
        ai_enabled=False,
    )[0]
    assert result.status == "matched"
    assert result.matched_item_id == 1
    assert result.suggestions["reason"] == "立创编号一致"


def test_exact_mpn_ignores_case_and_spaces():
    result = match_lines(
        [line(mpn="abc 123")],
        [item(mpn="ABC123", lcsc_code="")],
        ai_enabled=False,
    )[0]
    assert result.status == "matched"
    assert result.suggestions["reason"] == "厂家型号一致"


def test_insufficient_stock():
    result = match_lines(
        [line(lcsc_code="C1", quantity_required=20)],
        [item(lcsc_code="C1", quantity=5)],
        ai_enabled=False,
    )[0]
    assert result.status == "insufficient"


def test_multiple_hits_prefer_enough_stock_and_same_footprint():
    result = match_lines(
        [line(lcsc_code="C1", footprint="0603", quantity_required=10)],
        [
            item(id=1, lcsc_code="C1", footprint="1206", quantity=100),
            item(id=2, lcsc_code="C1", footprint="0603", quantity=3, mpn="LOW"),
            item(id=3, lcsc_code="C1", footprint="R0603", quantity=30, mpn="GOOD"),
        ],
        ai_enabled=False,
    )[0]
    assert result.matched_item_id == 3
    assert len(result.suggestions["exact_hits"]) == 3


def test_same_footprint_and_value_suggests_without_ai():
    result = match_lines(
        [line(mpn="0603WAF1002T5E", footprint="R0603", value="10kΩ", category="")],
        [item(id=7, mpn="OTHER", footprint="0603", value="10kΩ", category="电阻", box_name="A", row=1, col=2)],
        ai_enabled=False,
    )[0]
    assert result.status == "suggested"
    assert result.matched_item_id == 7
    assert "0603" in result.suggestions["reason"]
    assert "10kΩ" in result.suggestions["reason"]


def test_no_candidate_is_not_found():
    result = match_lines(
        [line(mpn="NONE", footprint="QFN-32", value="", category="连接器")],
        [item(mpn="OTHER", footprint="0603", value="10kΩ", category="电阻")],
        ai_enabled=False,
    )[0]
    assert result.status == "not_found"


def test_ai_drops_ids_outside_candidates(monkeypatch):
    def fake_suggest(lines):
        return {
            lines[0]["line_id"]: [
                {"item_id": 999, "suitable": True, "reason": "编造", "risks": []},
                {"item_id": 7, "suitable": True, "reason": "封装和阻值接近，需确认功率", "risks": ["功率", "不存在的风险"]},
            ]
        }

    monkeypatch.setattr("app.services.match.suggest", fake_suggest)
    result = match_lines(
        [line(id=4, mpn="0603WAF1002T5E", footprint="R0603", value="10kΩ")],
        [item(id=7, mpn="OTHER", footprint="0603", value="10kΩ")],
        ai_enabled=True,
    )[0]
    assert result.status == "suggested"
    assert result.matched_item_id == 7
    assert [row["item_id"] for row in result.suggestions["candidates"]] == [7]
    assert result.suggestions["risks"] == ["功率"]
    assert result.suggestions["source"] == "ai"
