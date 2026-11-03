from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.services.match import CATEGORY_RULES, category_tags, footprint_main

# 关键词搜索：把 "10k 0603" 这类输入拆成若干条件，全部满足才算命中。

OHM = "Ω"
_SPLIT = re.compile(r"[\s,，;；、]+")
_CJK_RUNS = re.compile(r"[一-鿿]+|[^一-鿿]+")
_PACKAGE = re.compile(
    r"^(?:0201|0402|0603|0805|1206|1210|1812|2010|2512"
    r"|(?:SOT|SOD|SOP|SOIC|SSOP|TSSOP|ESOP|MSOP|QFN|DFN|LQFP|TQFP|QFP|TO)-?\d+(?:FL)?"
    r"|SMA|SMB|SMC)$",
    re.IGNORECASE,
)
_NUM = r"(\d+(?:\.\d+)?)"
_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6}

# 单位 -> 需要的类目。电压、电流、功率、精度不限定类目。
UNIT_CATEGORY = {"ohm": "电阻", "F": "电容", "H": "电感"}
UNIT_SCALES = {
    "ohm": ((1e6, "MΩ"), (1e3, "kΩ"), (1.0, "Ω"), (1e-3, "mΩ")),
    "F": ((1e-6, "μF"), (1e-9, "nF"), (1e-12, "pF")),
    "H": ((1e-3, "mH"), (1e-6, "μH"), (1e-9, "nH")),
    "V": ((1e3, "kV"), (1.0, "V"), (1e-3, "mV")),
    "A": ((1.0, "A"), (1e-3, "mA"), (1e-6, "μA")),
    "W": ((1.0, "W"), (1e-3, "mW")),
    "%": ((1.0, "%"),),
}


def _prefixed(number: str, prefix: str) -> float:
    return float(number) * _SI[prefix]


def _rkm(head: str, tail: str, prefix: str) -> float:
    return float(f"{head}.{tail}") * _SI[prefix]


def _fraction(top: str, bottom: str, prefix: str) -> float | None:
    if float(bottom) == 0:
        return None
    return float(top) / float(bottom) * _SI[prefix]


# (单位, 正则, 取值函数)。正则只描述数值本身，前后边界在编译时补上。
_PATTERNS: tuple[tuple[str, str, object], ...] = (
    ("H", _NUM + r"\s*([numNU])[Hh]", lambda m: _prefixed(m.group(1), m.group(2).lower())),
    ("F", _NUM + r"\s*([pnumPNU])[Ff]", lambda m: _prefixed(m.group(1), m.group(2).lower())),
    ("F", _NUM + r"([pnu])", lambda m: _prefixed(m.group(1), m.group(2))),
    ("F", r"(\d+)([pnu])(\d{1,2})", lambda m: _rkm(m.group(1), m.group(3), m.group(2))),
    ("ohm", _NUM + r"\s*([mkKM]?)Ω", lambda m: _prefixed(m.group(1), m.group(2))),
    ("ohm", _NUM + r"([kKM])", lambda m: _prefixed(m.group(1), m.group(2))),
    ("ohm", _NUM + r"[Rr]", lambda m: float(m.group(1))),
    ("ohm", r"(\d+)([RrkKM])(\d+)", lambda m: _rkm(m.group(1), m.group(3), "" if m.group(2) in "Rr" else m.group(2))),
    ("V", _NUM + r"\s*([mkK]?)[Vv]", lambda m: _prefixed(m.group(1), m.group(2))),
    ("V", r"(\d+)[Vv](\d+)", lambda m: _rkm(m.group(1), m.group(2), "")),
    ("A", _NUM + r"\s*([um]?)A", lambda m: _prefixed(m.group(1), m.group(2))),
    ("W", _NUM + r"\s*([mM]?)[Ww]", lambda m: _prefixed(m.group(1), m.group(2).lower())),
    ("W", r"(\d+)/(\d+)\s*(m?)[Ww]", lambda m: _fraction(m.group(1), m.group(2), m.group(3))),
    ("%", r"(?:±|\+/-)?" + _NUM + r"\s*%", lambda m: float(m.group(1))),
)
_FULL = tuple((unit, re.compile(rf"^{body}$"), convert) for unit, body, convert in _PATTERNS)
_SCAN = tuple(
    (unit, re.compile(rf"(?<![0-9A-Za-z./]){body}(?![0-9A-Za-z])"), convert) for unit, body, convert in _PATTERNS
)


def normalize_text(text: str) -> str:
    value = (text or "").replace("μ", "u").replace("µ", "u")
    value = value.replace("Ω", OHM).replace("ω", OHM)
    value = re.sub(r"(?i)ohms?(?![a-z])", OHM, value)
    return value.replace("欧姆", OHM).replace("欧", OHM)


def parse_quantity(token: str) -> tuple[str, float] | None:
    for unit, pattern, convert in _FULL:
        found = pattern.match(token)
        if found:
            number = convert(found)
            if number is not None:
                return unit, number
    return None


def scan_quantities(text: str) -> dict[str, list[float]]:
    output: dict[str, list[float]] = {}
    blob = normalize_text(text)
    for unit, pattern, convert in _SCAN:
        for found in pattern.finditer(blob):
            number = convert(found)
            if number is not None:
                output.setdefault(unit, []).append(number)
    return output


def earliest_quantity(text: str, units: frozenset[str] | None = None) -> tuple[str, float, int] | None:
    """归一化文本里最靠前的数量，返回 (单位, 数值, 起点)。"""
    blob = normalize_text(text)
    best: tuple[int, int, str, float] | None = None
    for unit, pattern, convert in _SCAN:
        if units is not None and unit not in units:
            continue
        found = pattern.search(blob)
        if found is None:
            continue
        number = convert(found)
        if number is None:
            continue
        # 起点相同的时候保留更长的匹配，避免 10kΩ 被收成 10k。
        span = found.end() - found.start()
        if best is None or found.start() < best[0] or (found.start() == best[0] and span > best[1]):
            best = (found.start(), span, unit, float(number))
    if best is None:
        return None
    return best[2], best[3], best[0]


def format_quantity(unit: str, number: float) -> str:
    scales = UNIT_SCALES[unit]
    factor, suffix = scales[-1]
    for scale, name in scales:
        if abs(number) >= scale * 0.9999:
            factor, suffix = scale, name
            break
    shown = f"{number / factor:.4f}".rstrip("0").rstrip(".")
    if unit == "%":
        return f"±{shown}%"
    return f"{shown}{suffix}"


@dataclass
class Term:
    kind: str
    label: str
    text: str = ""
    unit: str = ""
    number: float = 0.0


@dataclass
class ItemView:
    code: str
    mpn: str
    category: str
    tags: set[str]
    haystack: str
    footprint: str
    package: str
    quantities: dict[str, list[float]] = field(default_factory=dict)


def item_view(item, specs: dict[str, str]) -> ItemView:
    category = (item.category or "").strip()
    name = item.name or ""
    spec_text = " ".join(str(value) for value in (specs or {}).values())
    footprint = item.footprint or ""
    haystack = " ".join(
        [
            item.lcsc_code or "",
            item.mpn or "",
            name,
            item.brand or "",
            footprint,
            category,
            item.value or "",
            item.params or "",
            item.remark or "",
            spec_text,
        ]
    )
    return ItemView(
        code=(item.lcsc_code or "").strip().upper(),
        mpn=(item.mpn or "").lower(),
        category=category.lower(),
        # 有类目时只看类目，避免 "Shielded" 里的 led 之类误判。
        tags=category_tags(category) if category else category_tags(name),
        haystack=normalize_text(haystack).lower(),
        footprint=footprint.lower(),
        package=footprint_main(footprint) if footprint.strip() else footprint_main(f"{item.mpn or ''} {name}"),
        quantities=scan_quantities(" ".join([item.value or "", item.params or "", spec_text, name])),
    )


def _vocabulary(category_names) -> dict[str, str]:
    words: dict[str, str] = {}
    for label, keys in CATEGORY_RULES:
        words[label.lower()] = label
        for key in keys:
            words.setdefault(key.lower(), label)
    words.setdefault("mos管", "MOS")
    for name in category_names or []:
        text = (name or "").strip()
        if text:
            words.setdefault(text.lower(), text)
    return words


def _has_cjk(text: str) -> bool:
    return any("一" <= char <= "鿿" for char in text)


def _category_label(token: str, words: dict[str, str]) -> str | None:
    lowered = token.lower()
    if lowered in words:
        return words[lowered]
    if not _has_cjk(token):
        return None
    for word in sorted(words, key=len, reverse=True):
        if len(word) >= 2 and word in lowered:
            return words[word]
    return None


def tokenize(query: str, words: dict[str, str] | None = None) -> list[str]:
    known = words or {}
    tokens: list[str] = []
    for part in _SPLIT.split(normalize_text(query)):
        if not part:
            continue
        if part.lower() in known or not _has_cjk(part):
            tokens.append(part)
            continue
        # "10k电阻0603" -> 10k / 电阻 / 0603；"AO3400电源" -> AO3400 / 电源
        tokens.extend(piece for piece in _CJK_RUNS.findall(part) if piece.strip())
    return tokens


def classify(token: str, words: dict[str, str]) -> Term:
    if re.fullmatch(r"C[1-9]\d*", token, re.IGNORECASE) and len(token) >= 3:
        code = token.upper()
        return Term("lcsc", f"立创编号 {code}", text=code)
    if _PACKAGE.match(token):
        main = footprint_main(token) or token.upper()
        return Term("package", f"封装 {main}", text=token.lower(), unit=main)
    quantity = parse_quantity(token)
    if quantity is not None:
        unit, number = quantity
        return Term("quantity", format_quantity(unit, number), text=token, unit=unit, number=number)
    label = _category_label(token, words)
    if label is not None:
        return Term("category", label, text=token.lower())
    return Term("text", f"包含“{token}”", text=token.lower())


@dataclass
class SearchPlan:
    terms: list[Term] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.terms)

    def hints(self) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, label: str) -> None:
            if (kind, label) not in seen:
                seen.add((kind, label))
                output.append({"kind": kind, "label": label})

        for term in self.terms:
            if term.kind == "category":
                add("category", term.label)
            elif term.kind == "quantity" and term.unit in UNIT_CATEGORY:
                add("category", UNIT_CATEGORY[term.unit])
        for term in self.terms:
            if term.kind == "quantity":
                add("value" if term.unit in UNIT_CATEGORY else "spec", term.label)
            elif term.kind in ("package", "lcsc", "text"):
                add(term.kind, term.label)
        return output

    def matches(self, view: ItemView) -> bool:
        return all(_term_matches(term, view) for term in self.terms)


def plan_query(query: str, category_names=()) -> SearchPlan:
    words = _vocabulary(category_names)
    return SearchPlan([classify(token, words) for token in tokenize(query, words)])


def _in_category(label: str, view: ItemView) -> bool:
    return label in view.tags or label.lower() in view.category


def _term_matches(term: Term, view: ItemView) -> bool:
    if term.kind == "lcsc":
        return view.code == term.text or term.text.lower() in view.mpn
    if term.kind == "package":
        return (bool(view.package) and view.package == term.unit) or term.text in view.footprint
    if term.kind == "category":
        return term.text in view.category or _in_category(term.label, view)
    if term.kind == "quantity":
        needed = UNIT_CATEGORY.get(term.unit)
        if needed and (view.category or view.tags) and not _in_category(needed, view):
            return False
        return any(
            math.isclose(found, term.number, rel_tol=1e-6, abs_tol=1e-15)
            for found in view.quantities.get(term.unit, [])
        )
    return term.text in view.haystack
