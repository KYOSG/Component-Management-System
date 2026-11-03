from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, StockEvent
from app.schemas import OrderLineIn
from app.services.bom import BomError, read_matrices
from app.services.search import earliest_quantity, format_quantity, normalize_text
from app.services.specs import SpecCatalog, dump_specs
from app.services.stock import change_quantity

_NOMINAL_UNITS = frozenset({"ohm", "F", "H"})
_HZ = re.compile(r"(?<![0-9A-Za-z./])(\d+(?:\.\d+)?)\s*([kKmMgG])?[Hh][Zz](?![0-9A-Za-z])")
_TOLERANCE = re.compile(r"(?:±|\+/-)\s*\d+(?:\.\d+)?\s*%")
_POWER = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*([mM]?[Ww])(?![A-Za-z])")
_VOLTAGE = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*([mMkK]?[Vv])(?![A-Za-z])")
_ORDER_NO = re.compile(r"SO\d+", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_EMPTY_CODE = {"", "-", "—", "无", "NONE", "NULL"}
_WITHHOLD = {"是", "不发", "不发货", "y", "yes", "true"}
_SKIP_TOTALS = {"合计", "总计", "小计"}
_OHM_BLOCK = ("磁珠", "滤波", "共模", "电感")
_VALUE_LABEL = {"resistor": "阻值", "capacitor": "容值", "inductor": "电感值"}
_SI = {"": 1.0, "k": 1e3, "K": 1e3, "m": 1e-3, "M": 1e6, "g": 1e9, "G": 1e9}


class OrderError(Exception):
    pass


@dataclass
class OrderLine:
    line_no: int
    lcsc_code: str = ""
    mpn: str = ""
    name: str = ""
    brand: str = ""
    footprint: str = ""
    category: str = ""
    value: str = ""
    params: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    ordered_qty: int = 0
    ship_qty: int = 0
    unit_price: float | None = None
    skip: bool = False
    skip_reason: str = ""


@dataclass
class ParsedOrder:
    order_no: str
    ordered_at: str
    lines: list[OrderLine]


@dataclass
class PreviewLine:
    line_no: int
    lcsc_code: str
    mpn: str
    name: str
    brand: str
    footprint: str
    category: str
    value: str
    ordered_qty: int
    ship_qty: int
    unit_price: float | None
    skip: bool
    skip_reason: str
    action: str
    current_quantity: int


@dataclass
class OrderPreview:
    order_no: str
    ordered_at: str
    lines: list[PreviewLine]
    create_count: int
    stock_count: int
    skip_count: int
    ship_total: int


@dataclass
class ApplyResult:
    created: int
    stocked: int
    skipped: int
    ship_total: int


def order_note(order_no: str) -> str:
    text = (order_no or "").strip()
    if text:
        return f"订单入库 {text}"
    return "订单入库"


def parse_order(filename: str, data: bytes, catalog: SpecCatalog) -> ParsedOrder:
    try:
        matrices = read_matrices(filename, data)
    except BomError as exc:
        raise OrderError(str(exc)) from exc
    saw_header = False
    best: ParsedOrder | None = None
    for matrix in matrices:
        parsed = _parse_matrix(matrix, filename, catalog)
        if parsed is None:
            continue
        saw_header = True
        if best is None or len(parsed.lines) > len(best.lines):
            best = parsed
    if not saw_header or best is None:
        raise OrderError("无法识别订单文件，请上传立创商城订单详情")
    if not best.lines:
        raise OrderError("没有可入库的发货明细")
    return best


def build_preview(parsed: ParsedOrder, quantities: dict[str, int]) -> OrderPreview:
    running: dict[str, int] = {}
    lines: list[PreviewLine] = []
    create_count = 0
    stock_count = 0
    skip_count = 0
    ship_total = 0
    for line in parsed.lines:
        code = line.lcsc_code
        if line.skip or line.ship_qty <= 0:
            action = "skip"
            current = quantities.get(code, 0) if code else 0
            skip_count += 1
        elif code and (code in quantities or code in running):
            action = "stock"
            current = quantities.get(code, 0) + running.get(code, 0)
            stock_count += 1
            ship_total += line.ship_qty
        else:
            action = "create"
            current = 0
            create_count += 1
            ship_total += line.ship_qty
        if action != "skip" and code:
            running[code] = running.get(code, 0) + line.ship_qty
        lines.append(
            PreviewLine(
                line_no=line.line_no,
                lcsc_code=code,
                mpn=line.mpn,
                name=line.name,
                brand=line.brand,
                footprint=line.footprint,
                category=line.category,
                value=line.value,
                ordered_qty=line.ordered_qty,
                ship_qty=line.ship_qty,
                unit_price=line.unit_price,
                skip=action == "skip",
                skip_reason=line.skip_reason if action == "skip" else "",
                action=action,
                current_quantity=current,
            )
        )
    return OrderPreview(
        order_no=parsed.order_no,
        ordered_at=parsed.ordered_at,
        lines=lines,
        create_count=create_count,
        stock_count=stock_count,
        skip_count=skip_count,
        ship_total=ship_total,
    )


def apply_order(
    db: Session,
    user_id: int,
    catalog: SpecCatalog,
    order_no: str,
    lines: list[OrderLineIn],
) -> ApplyResult:
    created = 0
    stocked = 0
    skipped = 0
    ship_total = 0
    note = order_note(order_no)
    for line in lines:
        if line.skip or line.ship_qty <= 0:
            skipped += 1
            continue
        code = _code(line.lcsc_code)
        name = _clip(line.name, 255)
        mpn = _clip(line.mpn, 255)
        brand = _clip(line.brand, 255)
        footprint = _clip(line.footprint, 255)
        if not any((code, mpn, name)):
            skipped += 1
            continue
        item = None
        if code:
            item = db.scalar(select(Item).where(Item.user_id == user_id, Item.lcsc_code == code))
        if item is None:
            category, value, params, specs = describe_product(name, catalog)
            item = Item(
                user_id=user_id,
                lcsc_code=code or None,
                mpn=mpn,
                name=name,
                brand=brand,
                footprint=footprint,
                category=_clip(category, 255),
                value=_clip(value, 255),
                params=params,
                specs=dump_specs(specs),
                unit_price=line.unit_price,
                quantity=0,
            )
            db.add(item)
            db.flush()
            created += 1
        else:
            stocked += 1
        change_quantity(db, user_id, item, line.ship_qty, positive="stock_in", note=note)
        ship_total += line.ship_qty
    if created == 0 and stocked == 0:
        raise OrderError("没有可入库的发货明细")
    return ApplyResult(created=created, stocked=stocked, skipped=skipped, ship_total=ship_total)


def already_imported(db: Session, user_id: int, order_no: str) -> bool:
    found = db.scalar(
        select(StockEvent.id).where(StockEvent.user_id == user_id, StockEvent.note == order_note(order_no)).limit(1)
    )
    return found is not None


def describe_product(name: str, catalog: SpecCatalog) -> tuple[str, str, str, dict[str, str]]:
    unit, number = _nominal(name)
    value = _format_nominal(unit, number) if unit else ""
    category = _category(catalog, name, unit)
    kind = _kind(unit, category)
    params, specs = _details(catalog, category, kind, name, value)
    return category, value, params, specs


def _parse_matrix(matrix: list[list[str]], filename: str, catalog: SpecCatalog) -> ParsedOrder | None:
    header_index = _find_header(matrix)
    if header_index is None:
        return None
    columns = _headers(matrix[header_index])
    lines: list[OrderLine] = []
    for row in matrix[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        code = _code(_pick(row, columns, "商品编号"))
        mpn = _clip(_pick(row, columns, "厂家型号"), 255)
        name = _clip(_pick(row, columns, "商品名称"), 255)
        brand = _clip(_pick(row, columns, "品牌"), 255)
        footprint = _clip(_pick(row, columns, "封装"), 255)
        ordered = _count(_pick(row, columns, "订购数量（修改后）", "订购数量(修改后)", "订购数量"))
        ship = _count(_pick(row, columns, "发货数量"))
        price = _money(_pick(row, columns, "商品单价"))
        if code in _SKIP_TOTALS or (not code and name in _SKIP_TOTALS):
            continue
        if not any((code, mpn, name)):
            continue
        withheld = _withhold(_pick(row, columns, "是否不发此货"))
        if withheld:
            skip = True
            reason = "不发此货"
        elif ship <= 0:
            skip = True
            reason = "发货数量为 0"
        else:
            skip = False
            reason = ""
        category, value, params, specs = describe_product(name, catalog)
        serial = _count(_pick(row, columns, "序号"))
        lines.append(
            OrderLine(
                line_no=serial or len(lines) + 1,
                lcsc_code=code,
                mpn=mpn,
                name=name,
                brand=brand,
                footprint=footprint,
                category=category,
                value=value,
                params=params,
                specs=specs,
                ordered_qty=ordered,
                ship_qty=ship,
                unit_price=price,
                skip=skip,
                skip_reason=reason,
            )
        )
    order_no = _labeled(matrix, header_index, "订单编号") or _order_from_name(filename)
    ordered_at = _labeled(matrix, header_index, "下单日期")
    return ParsedOrder(order_no=order_no, ordered_at=ordered_at, lines=lines)


def _nominal(name: str) -> tuple[str, float]:
    blob = normalize_text(name)
    measure = earliest_quantity(blob, _NOMINAL_UNITS)
    hz_value = _leading_hz(blob)
    if measure and hz_value:
        if measure[2] <= hz_value[2]:
            return measure[0], measure[1]
        return "Hz", hz_value[1]
    if measure:
        return measure[0], measure[1]
    if hz_value:
        return "Hz", hz_value[1]
    return "", 0.0


def _leading_hz(blob: str) -> tuple[str, float, int] | None:
    # 只认写在名称开头的频率，避免 MCU 描述里的 “72 MHz CPU” 被当成标称值。
    found = _HZ.search(blob)
    if found is None:
        return None
    prefix = blob[: found.start()].strip()
    if len(prefix) > 12 or any(mark in prefix for mark in "，,、;；"):
        return None
    number = float(found.group(1)) * _SI.get(found.group(2) or "", 1.0)
    return "Hz", number, found.start()


def _format_nominal(unit: str, number: float) -> str:
    if unit == "ohm" and number == 0:
        return "0Ω"
    if unit == "Hz":
        return _format_hz(number)
    return format_quantity(unit, number)


def _format_hz(number: float) -> str:
    if number >= 1_000_000_000:
        return _trim(number / 1_000_000_000) + "GHz"
    if number >= 1_000_000:
        return _trim(number / 1_000_000) + "MHz"
    if number >= 1_000:
        return _trim(number / 1_000) + "kHz"
    return _trim(number) + "Hz"


def _trim(number: float) -> str:
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _category(catalog: SpecCatalog, name: str, unit: str) -> str:
    if unit == "Hz":
        return ""
    if unit == "ohm":
        if any(word in name for word in _OHM_BLOCK):
            return ""
        return _by_keyword(catalog, "电阻")
    if unit == "F":
        return _by_keyword(catalog, "电容")
    if unit == "H":
        return _by_keyword(catalog, "电感")
    if unit:
        return ""
    mapped = catalog.map_category(name)
    if mapped in {category.name for category in catalog.categories}:
        return mapped
    if "沟道" in name:
        return _by_keyword(catalog, "mos")
    return ""


def _by_keyword(catalog: SpecCatalog, needle: str) -> str:
    wanted = needle.lower()
    for category in catalog.categories:
        if category.name.lower() == wanted:
            return category.name
        if any(wanted in (keyword or "").lower() for keyword in category.lcsc_keywords):
            return category.name
    return ""


def _kind(unit: str, category: str) -> str:
    if not category:
        return ""
    if unit == "ohm":
        return "resistor"
    if unit == "F":
        return "capacitor"
    if unit == "H":
        return "inductor"
    return ""


def _details(catalog: SpecCatalog, category: str, kind: str, name: str, value: str) -> tuple[str, dict[str, str]]:
    pairs: list[tuple[str, str]] = []
    label = _VALUE_LABEL.get(kind, "")
    if label and value:
        pairs.append((label, value))
    if kind in {"resistor", "capacitor", "inductor"}:
        tolerance = _TOLERANCE.search(name)
        if tolerance:
            pairs.append(("精度", re.sub(r"\s+", "", tolerance.group(0))))
    if kind == "resistor":
        power = _POWER.search(name)
        if power:
            pairs.append(("功率", f"{power.group(1)}{power.group(2)}"))
    if kind == "capacitor":
        voltage = _VOLTAGE.search(name)
        if voltage:
            pairs.append(("额定电压", f"{voltage.group(1)}{voltage.group(2)}"))
    specs = catalog.extract(category, pairs) if category else {}
    params = "；".join(f"{key}：{text}" for key, text in pairs)
    return params, specs


def _find_header(matrix: list[list[str]]) -> int | None:
    required = {"商品编号", "发货数量"}
    for index, row in enumerate(matrix[:80]):
        if required <= set(_headers(row)):
            return index
    return None


def _headers(row: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(row):
        key = _key(cell)
        if key and key not in found:
            found[key] = index
    return found


def _key(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").replace("\u3000", "").replace("\u00a0", "")).lower()


def _pick(row: list[str], columns: dict[str, int], *names: str) -> str:
    for name in names:
        position = columns.get(_key(name))
        if position is not None and position < len(row):
            return row[position].strip()
    return ""


def _labeled(matrix: list[list[str]], header_index: int, label: str) -> str:
    for row in matrix[:header_index]:
        for index, cell in enumerate(row):
            text = cell.strip()
            for mark in ("：", ":"):
                prefix = f"{label}{mark}"
                if text.startswith(prefix) and text[len(prefix) :].strip():
                    return text[len(prefix) :].strip()
            if text in {label, f"{label}：", f"{label}:"}:
                if index + 1 < len(row):
                    return row[index + 1].strip()
                return ""
    return ""


def _order_from_name(filename: str) -> str:
    found = _ORDER_NO.search(filename or "")
    return found.group(0).upper() if found else ""


def _code(value: str) -> str:
    text = (value or "").strip().upper()
    if text in _EMPTY_CODE:
        return ""
    return text[:64]


def _clip(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]


def _count(value: str) -> int:
    found = _NUMBER.search((value or "").replace(",", "").replace("，", ""))
    if not found:
        return 0
    return int(round(float(found.group(0))))


def _money(value: str) -> float | None:
    found = _NUMBER.search((value or "").replace(",", "").replace("，", ""))
    if not found:
        return None
    return round(float(found.group(0)), 6)


def _withhold(value: str) -> bool:
    return value.strip().lower() in _WITHHOLD
