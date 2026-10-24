from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.deepseek import suggest

CHIP_SIZES = ("0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512")
ALLOWED_RISKS = {"耐压", "精度", "功率", "温度", "封装", "库存"}
CATEGORY_RULES = (
    ("电阻", ("电阻", "resistor")),
    ("电容", ("电容", "capacitor")),
    ("电感", ("电感", "inductor")),
    ("二极管", ("二极管", "diode")),
    ("MOS", ("mosfet", "mos")),
    ("三极管", ("三极管", "transistor")),
    ("LED", ("led", "发光")),
    ("连接器", ("连接器", "connector")),
    ("电源", ("电源", "ldo", "regulator")),
)


@dataclass
class ItemSnap:
    id: int
    lcsc_code: str = ""
    mpn: str = ""
    name: str = ""
    brand: str = ""
    footprint: str = ""
    category: str = ""
    value: str = ""
    params: str = ""
    quantity: int = 0
    box_name: str = ""
    row: int | None = None
    col: int | None = None


@dataclass
class LineSnap:
    id: int
    designators: str = ""
    quantity_per_board: int = 0
    quantity_required: int = 0
    lcsc_code: str = ""
    mpn: str = ""
    brand: str = ""
    footprint: str = ""
    value: str = ""
    params: str = ""
    product_name: str = ""
    category: str = ""


@dataclass
class Candidate:
    item: ItemSnap
    signals: int
    footprint_match: bool
    value_match: bool
    categories: set[str] = field(default_factory=set)
    risks: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class MatchResult:
    status: str
    matched_item_id: int | None
    suggestions: dict


def footprint_main(text: str) -> str:
    raw = (text or "").upper().replace(" ", "")
    if not raw:
        return ""
    for size in CHIP_SIZES:
        if re.search(rf"(^|[^0-9]){size}([^0-9]|$)", raw):
            return size
    sot = re.search(r"SOT-?(\d+)", raw)
    if sot:
        return f"SOT-{sot.group(1)}"
    sod = re.search(r"SOD-?(\d+)(FL)?", raw)
    if sod:
        return f"SOD-{sod.group(1)}{sod.group(2) or ''}"
    named = re.search(r"(SOP|SOIC|SSOP|TSSOP|ESOP|MSOP|QFN|DFN|LQFP|TQFP|QFP|TO)-?(\d+)", raw)
    if named:
        return f"{named.group(1)}-{named.group(2)}"
    simple = re.match(r"^(SMA|SMB|SMC)(?:_|-|$)", raw)
    if simple:
        return simple.group(1)
    return ""


def norm_mpn(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def norm_value(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("μ", "u").replace("µ", "u").replace("ω", "ohm").replace("Ω", "ohm")
    text = re.sub(r"\s+", "", text)
    text = text.replace("ohms", "ohm").replace("ohm", "")
    return text


def category_tags(text: str) -> set[str]:
    blob = (text or "").lower()
    return {label for label, keys in CATEGORY_RULES if any(key.lower() in blob for key in keys)}


def match_lines(lines: list[LineSnap], items: list[ItemSnap], *, ai_enabled: bool) -> list[MatchResult]:
    drafts: list[tuple[str, LineSnap, list[ItemSnap], list[Candidate]]] = []
    for line in lines:
        hits = _exact_hits(line, items)
        if hits:
            drafts.append(("exact", line, hits, []))
            continue
        drafts.append(("open", line, [], _rank_candidates(line, items)))

    ai_map: dict[int, list[dict] | None] = {}
    if ai_enabled:
        payload = [_ai_payload(line, ranked) for kind, line, _hits, ranked in drafts if kind == "open" and ranked]
        if payload:
            ai_map = suggest(payload)

    results: list[MatchResult] = []
    for kind, line, hits, ranked in drafts:
        if kind == "exact":
            results.append(_exact_result(line, hits))
            continue
        ai_picks = ai_map.get(line.id) if ai_enabled and ranked else None
        if ai_enabled and ranked and line.id in ai_map and ai_picks is not None:
            results.append(_ai_result(line, ranked, ai_picks))
        else:
            results.append(_rule_result(line, ranked))
    return results


def _exact_hits(line: LineSnap, items: list[ItemSnap]) -> list[ItemSnap]:
    code = (line.lcsc_code or "").strip().lower()
    mpn = norm_mpn(line.mpn)
    found: list[ItemSnap] = []
    seen: set[int] = set()
    for item in items:
        matched = False
        if code and (item.lcsc_code or "").strip().lower() == code:
            matched = True
        elif mpn and norm_mpn(item.mpn) == mpn:
            matched = True
        if matched and item.id not in seen:
            seen.add(item.id)
            found.append(item)
    return found


def _footprint_compatible(line: LineSnap, item: ItemSnap) -> bool:
    left = footprint_main(line.footprint)
    right = footprint_main(item.footprint)
    if left and right:
        return left == right
    return bool(line.footprint) and line.footprint.strip().lower() == item.footprint.strip().lower()


def _exact_result(line: LineSnap, hits: list[ItemSnap]) -> MatchResult:
    chosen = max(
        hits,
        key=lambda item: (
            item.quantity >= line.quantity_required and _footprint_compatible(line, item),
            item.quantity >= line.quantity_required,
            _footprint_compatible(line, item),
            item.quantity,
            -item.id,
        ),
    )
    by_code = (line.lcsc_code or "").strip() and (chosen.lcsc_code or "").strip().lower() == line.lcsc_code.strip().lower()
    reason = "立创编号一致" if by_code else "厂家型号一致"
    status = "insufficient" if chosen.quantity < line.quantity_required else "matched"
    ordered = [chosen] + [item for item in hits if item.id != chosen.id]
    return MatchResult(
        status=status,
        matched_item_id=chosen.id,
        suggestions={
            "source": "exact",
            "reason": reason,
            "risks": [],
            "exact_hits": [_brief(item, True, reason, []) for item in ordered],
            "candidates": [],
        },
    )


def _rank_candidates(line: LineSnap, items: list[ItemSnap]) -> list[Candidate]:
    exact_ids = {item.id for item in _exact_hits(line, items)}
    line_footprint = footprint_main(line.footprint)
    line_value = norm_value(line.value)
    line_categories = category_tags(line.category) or category_tags(line.product_name)
    ranked: list[Candidate] = []
    for item in items:
        if item.id in exact_ids:
            continue
        item_footprint = footprint_main(item.footprint)
        footprint_match = bool(line_footprint and item_footprint and line_footprint == item_footprint)
        value_match = bool(line_value and norm_value(item.value) == line_value)
        item_categories = category_tags(item.category) or category_tags(item.name)
        shared = line_categories & item_categories
        if not (footprint_match or value_match or shared):
            continue
        risks: list[str] = []
        if line_footprint and item_footprint and not footprint_match:
            risks.append("封装")
        if line_categories and item_categories and not shared:
            risks.append("类目")
        reason_parts: list[str] = []
        if footprint_match:
            reason_parts.append(f"封装主名同为 {line_footprint}")
        if value_match:
            reason_parts.append(f"标称值同为 {line.value or item.value}")
        if shared:
            reason_parts.append("类目相同（" + "、".join(sorted(shared)) + "）")
        ranked.append(
            Candidate(
                item=item,
                signals=int(footprint_match) + int(value_match) + int(bool(shared)),
                footprint_match=footprint_match,
                value_match=value_match,
                categories=shared,
                risks=risks,
                reason="，".join(reason_parts),
            )
        )
    ranked.sort(key=lambda row: (-row.signals, -row.item.quantity, row.item.id))
    return ranked[:20]


def _rule_result(line: LineSnap, ranked: list[Candidate]) -> MatchResult:
    if not ranked:
        return MatchResult(status="not_found", matched_item_id=None, suggestions=_empty("rule"))
    candidates = [_brief(row.item, True, row.reason, row.risks) for row in ranked]
    return MatchResult(
        status="suggested",
        matched_item_id=ranked[0].item.id,
        suggestions={
            "source": "rule",
            "reason": ranked[0].reason,
            "risks": ranked[0].risks,
            "exact_hits": [],
            "candidates": candidates,
        },
    )


def _ai_result(line: LineSnap, ranked: list[Candidate], picks: list[dict]) -> MatchResult:
    by_id = {row.item.id: row for row in ranked}
    candidates = []
    for pick in picks:
        row = by_id.get(pick["item_id"])
        if row is None:
            continue
        reason = pick["reason"] or row.reason
        raw_risks = pick.get("risks") or []
        risks = [risk for risk in raw_risks if risk in ALLOWED_RISKS] or row.risks
        candidates.append(_brief(row.item, True, reason, risks))
    if not candidates:
        return MatchResult(status="not_found", matched_item_id=None, suggestions=_empty("ai"))
    return MatchResult(
        status="suggested",
        matched_item_id=candidates[0]["item_id"],
        suggestions={
            "source": "ai",
            "reason": candidates[0]["reason"],
            "risks": candidates[0]["risks"],
            "exact_hits": [],
            "candidates": candidates,
        },
    )


def _ai_payload(line: LineSnap, ranked: list[Candidate]) -> dict:
    return {
        "line_id": line.id,
        "designators": line.designators,
        "lcsc_code": line.lcsc_code,
        "mpn": line.mpn,
        "footprint": line.footprint,
        "value": line.value,
        "category": line.category,
        "params": line.params,
        "product_name": line.product_name,
        "quantity_required": line.quantity_required,
        "candidates": [
            {
                "item_id": row.item.id,
                "mpn": row.item.mpn,
                "name": row.item.name,
                "footprint": row.item.footprint,
                "value": row.item.value,
                "category": row.item.category,
                "params": row.item.params,
                "quantity": row.item.quantity,
                "box_name": row.item.box_name,
                "rule_reason": row.reason,
            }
            for row in ranked
        ],
    }


def _brief(item: ItemSnap, suitable: bool, reason: str, risks: list[str]) -> dict:
    return {
        "item_id": item.id,
        "lcsc_code": item.lcsc_code,
        "mpn": item.mpn,
        "name": item.name,
        "footprint": item.footprint,
        "value": item.value,
        "category": item.category,
        "quantity": item.quantity,
        "box_name": item.box_name,
        "row": item.row,
        "col": item.col,
        "suitable": suitable,
        "reason": reason,
        "risks": risks,
    }


def _empty(source: str) -> dict:
    return {"source": source, "reason": "", "risks": [], "exact_hits": [], "candidates": []}
