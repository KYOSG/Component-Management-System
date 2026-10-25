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


def test_disabled_ai_skips_exact_and_rules():
    exact = match_lines(
        [line(lcsc_code="C105580", mpn="OTHER")],
        [item(lcsc_code="C105580", mpn="RC0603FR-075K1L", quantity=50)],
        ai_enabled=False,
    )[0]
    assert exact.status == ""
    assert exact.matched_item_id is None
    assert exact.suggestions["exact_hits"] == []
    assert exact.suggestions["candidates"] == []
    suggested = match_lines(
        [line(mpn="0603WAF1002T5E", footprint="R0603", value="10kΩ", category="")],
        [item(id=7, mpn="OTHER", footprint="0603", value="10kΩ", category="电阻")],
        ai_enabled=False,
    )[0]
    assert suggested.status == ""
    assert suggested.matched_item_id is None
    assert suggested.suggestions["candidates"] == []


def test_local_match_leaves_ai_pending_without_calling_model(monkeypatch):
    from app.services.match import local_match_lines

    called = []
    monkeypatch.setattr("app.services.match.suggest", lambda *_args, **_kwargs: called.append(1))
    result = local_match_lines(
        [line(mpn="0603WAF1002T5E", footprint="R0603", value="10kΩ")],
        [item(id=7, mpn="OTHER", footprint="0603", value="10kΩ")],
        ai_enabled=True,
    )[0]
    assert called == []
    assert result.status == ""
    assert result.suggestions["source"] == "pending"
    assert result.suggestions["candidates"] == []


def test_exact_code_matches():
    result = match_lines(
        [line(lcsc_code="C105580", mpn="OTHER")],
        [item(lcsc_code="C105580", mpn="RC0603FR-075K1L", quantity=50)],
        ai_enabled=True,
    )[0]
    assert result.status == "matched"
    assert result.matched_item_id == 1
    assert result.suggestions["reason"] == ""


def test_lcsc_match_is_not_sent_to_ai(monkeypatch):
    sent = []

    def fake_suggest(lines, **_kwargs):
        sent.append([row["line_id"] for row in lines])
        return {int(lines[0]["line_id"]): [{"item_id": 7, "suitable": True, "reason": "耐压覆盖需求", "risks": ["耐压"]}]}

    monkeypatch.setattr("app.services.match.suggest", fake_suggest)
    results = match_lines(
        [
            line(id=1, lcsc_code="C1", mpn="BOM-CODE"),
            line(id=2, mpn="OTHER-BOM", footprint="R0603", value="10kΩ", lcsc_code=""),
        ],
        [
            item(id=3, lcsc_code="C1", mpn="LIB-CODE", quantity=20),
            item(id=7, mpn="OTHER", footprint="0603", value="10kΩ"),
        ],
        ai_enabled=True,
    )
    assert sent == [[2]]
    assert results[0].status == "matched"
    assert results[0].matched_item_id == 3
    assert results[1].status == "suggested"
    assert results[1].matched_item_id == 7


def test_exact_mpn_ignores_case_and_spaces():
    result = match_lines(
        [line(mpn="abc 123")],
        [item(mpn="ABC123", lcsc_code="")],
        ai_enabled=True,
    )[0]
    assert result.status == "matched"
    assert result.suggestions["reason"] == "厂家型号一致"


def test_insufficient_stock():
    result = match_lines(
        [line(lcsc_code="C1", quantity_required=20)],
        [item(lcsc_code="C1", quantity=5)],
        ai_enabled=True,
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
        ai_enabled=True,
    )[0]
    assert result.matched_item_id == 3
    assert len(result.suggestions["exact_hits"]) == 3


def test_ai_failure_gives_no_suggestion(monkeypatch):
    def fake_suggest(lines, **_kwargs):
        return {int(lines[0]["line_id"]): None}

    monkeypatch.setattr("app.services.match.suggest", fake_suggest)
    result = match_lines(
        [line(mpn="0603WAF1002T5E", footprint="R0603", value="10kΩ", category="")],
        [item(id=7, mpn="OTHER", footprint="0603", value="10kΩ", category="电阻", box_name="A", row=1, col=2)],
        ai_enabled=True,
    )[0]
    assert result.status == "not_found"
    assert result.matched_item_id is None
    assert result.suggestions["candidates"] == []
    assert result.suggestions["reason"] == ""


def test_no_candidate_skips_ai(monkeypatch):
    called = []

    def fake_suggest(lines, **_kwargs):
        called.append(lines)
        return {}

    monkeypatch.setattr("app.services.match.suggest", fake_suggest)
    result = match_lines(
        [line(mpn="NONE", footprint="QFN-32", value="", category="连接器")],
        [item(mpn="OTHER", footprint="0603", value="10kΩ", category="电阻")],
        ai_enabled=True,
    )[0]
    assert called == []
    assert result.status == "not_found"
    assert result.suggestions["candidates"] == []


def test_ai_drops_ids_outside_candidates(monkeypatch):
    def fake_suggest(lines, **_kwargs):
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
