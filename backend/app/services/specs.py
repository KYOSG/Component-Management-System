from __future__ import annotations

import json
import re
from dataclasses import dataclass

# 新用户的默认类目。字段类型默认 text，沿用原来的自由文本。
# key, 显示名, 立创/BOM 参数名别名。匹配前会去掉空格和标点并转小写。
_DEFAULT_FIELDS: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    "电阻": [
        ("tolerance", "精度", ("精度", "阻值精度", "公差", "tolerance", "resistance tolerance")),
        ("power", "功率", ("功率", "额定功率", "功率耗散", "power", "power rating")),
        ("tempco", "温度系数", ("温度系数", "temperature coefficient", "tcr")),
    ],
    "电容": [
        ("voltage", "额定电压", ("额定电压", "耐压", "voltage rating", "rated voltage")),
        ("tempco", "温度系数", ("温度系数", "temperature coefficient")),
        ("tolerance", "精度", ("精度", "容值精度", "公差", "tolerance", "capacitance tolerance")),
    ],
    "电感": [
        (
            "irms",
            "温升电流Irms",
            (
                "温升电流",
                "irms",
                "temperature rise current",
                "heat rating current",
                "current rating",
                "额定电流",
            ),
        ),
        ("isat", "饱和电流Isat", ("饱和电流", "saturation current", "isat")),
        ("dcr", "直流电阻DCR", ("直流电阻", "dcr", "dc resistance")),
    ],
    "二极管": [
        ("vr", "反向耐压", ("反向耐压", "反向电压", "反向重复峰值电压", "vr", "vrrm", "reverse voltage", "repetitive reverse voltage")),
        ("if", "正向电流", ("正向电流", "平均整流电流", "forward current", "average rectified current")),
    ],
    "MOS": [
        (
            "vds",
            "漏源耐压",
            ("漏源耐压", "漏源电压", "漏源击穿电压", "vds", "vdss", "drain-source voltage", "drain source voltage"),
        ),
        ("id", "连续漏极电流", ("连续漏极电流", "漏极电流", "continuous drain current", "id")),
        (
            "rds",
            "导通电阻",
            ("导通电阻", "rds(on)", "rds（on）", "drain-source on resistance", "drain source on-resistance"),
        ),
    ],
    "三极管": [
        (
            "vceo",
            "集电极-发射极耐压",
            (
                "集电极-发射极耐压",
                "集电极-发射极击穿电压",
                "集射极耐压",
                "集电极发射极耐压",
                "vceo",
                "collector-emitter voltage",
                "collector emitter voltage",
            ),
        ),
        ("ic", "集电极电流", ("集电极电流", "collector current", "ic")),
    ],
}

# 只用立创最后一级目录名归类，不看父目录。连接器和电源没有结构化字段，只参与归类。
_DEFAULT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("电阻", ("resistor", "电阻")),
    ("电容", ("capacitor", "电容")),
    ("电感", ("inductor", "电感")),
    ("二极管", ("diode", "二极管")),
    ("MOS", ("mosfet", "mos管", "mos")),
    ("三极管", ("transistor", "三极管")),
    ("连接器", ("connector", "连接器")),
    ("电源", ("power management", "电源")),
)

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
FIELD_TYPES = ("text", "number", "select")


class SpecValidationError(Exception):
    pass


@dataclass(frozen=True)
class SpecField:
    key: str
    label: str
    type: str = "text"
    unit: str = ""
    options: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class CatalogCategory:
    name: str
    lcsc_keywords: tuple[str, ...]
    fields: tuple[SpecField, ...]


def field_to_dict(field: SpecField) -> dict:
    return {
        "key": field.key,
        "label": field.label,
        "type": field.type,
        "unit": field.unit,
        "options": list(field.options),
        "aliases": list(field.aliases),
        "required": field.required,
    }


def _text_field(key: str, label: str, aliases: tuple[str, ...]) -> SpecField:
    return SpecField(key=key, label=label, type="text", aliases=aliases)


def default_catalog() -> SpecCatalog:
    categories = [
        CatalogCategory(
            name=name,
            lcsc_keywords=keywords,
            fields=tuple(_text_field(*item) for item in _DEFAULT_FIELDS.get(name, [])),
        )
        for name, keywords in _DEFAULT_KEYWORDS
    ]
    return SpecCatalog(categories)


class SpecCatalog:
    def __init__(self, categories: list[CatalogCategory]):
        self.categories = tuple(categories)
        self._by_name = {category.name: category for category in self.categories}

    def fields_for(self, category: str) -> tuple[SpecField, ...]:
        found = self._by_name.get((category or "").strip())
        return found.fields if found else ()

    def map_category(self, catalog: str) -> str:
        blob = (catalog or "").strip().lower()
        if blob:
            for category in self.categories:
                if any(keyword.lower() in blob for keyword in category.lcsc_keywords if keyword):
                    return category.name
        return (catalog or "").strip()

    def extract(self, category: str, pairs: list[tuple[str, str]]) -> dict[str, str]:
        return self.clean(category, self._match(category, pairs), strict=False)

    def clean(self, category: str, specs: dict | None, strict: bool = False) -> dict[str, str]:
        incoming = specs or {}
        output: dict[str, str] = {}
        errors: list[str] = []
        for field in self.fields_for(category):
            text = str(incoming.get(field.key) or "").strip()
            if not text:
                if strict and field.required:
                    errors.append(f"请填写{field.label}")
                continue
            normalized = _normalize(field, text)
            if normalized is None:
                if strict:
                    errors.append(_invalid_message(field))
                continue
            output[field.key] = normalized
        if strict and errors:
            raise SpecValidationError("；".join(errors))
        return output

    def present(self, category: str, stored: dict[str, str], params: str) -> dict[str, str]:
        merged = dict(stored or {})
        for key, value in self._match(category, parse_params(params)).items():
            merged.setdefault(key, value)
        output: dict[str, str] = {}
        for field in self.fields_for(category):
            text = str(merged.get(field.key) or "").strip()
            if not text:
                continue
            normalized = _normalize(field, text)
            output[field.key] = normalized if normalized is not None else text
        return output

    def _match(self, category: str, pairs: list[tuple[str, str]]) -> dict[str, str]:
        fields = self.fields_for(category)
        if not fields:
            return {}
        lookup: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name, value in pairs:
            key = _norm(name)
            text = (value or "").strip()
            if key and text and key not in seen:
                seen.add(key)
                lookup.append((key, text))
        output: dict[str, str] = {}
        for field in fields:
            aliases = field.aliases or (field.label, field.key)
            ordered = sorted(aliases, key=lambda alias: len(_norm(alias)), reverse=True)
            found = ""
            for alias in ordered:
                needle = _norm(alias)
                for param_name, text in lookup:
                    if _alias_hit(param_name, needle):
                        found = text
                        break
                if found:
                    break
            if found:
                output[field.key] = found
        return output


def _invalid_message(field: SpecField) -> str:
    if field.type == "number":
        return f"{field.label}需要是数字"
    if field.type == "select":
        return f"{field.label}不在可选项内"
    return f"{field.label}不正确"


def _normalize(field: SpecField, value: str) -> str | None:
    if field.type == "number":
        return _as_number(value, field.unit)
    if field.type == "select":
        text = value.strip()
        for option in field.options:
            if text == option:
                return option
        return None
    return value.strip()


def _as_number(value: str, unit: str) -> str | None:
    text = value.strip()
    suffix = (unit or "").strip()
    if suffix and text.endswith(suffix):
        text = text[: -len(suffix)].strip()
    if not text or _NUMBER.fullmatch(text) is None:
        return None
    return text


def _norm(name: str) -> str:
    text = (name or "").strip().lower().replace("μ", "u").replace("µ", "u")
    return re.sub(r"[\s\-_/（）()·.]+", "", text)


def parse_params(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in re.split(r"[;；\n]+", text or ""):
        if "：" in part:
            name, value = part.split("：", 1)
        elif ":" in part:
            name, value = part.split(":", 1)
        else:
            continue
        name = name.strip()
        value = value.strip()
        if name and value:
            pairs.append((name, value))
    return pairs


def _alias_hit(name: str, alias: str) -> bool:
    if not alias:
        return False
    if name == alias:
        return True
    if len(alias) <= 2:
        return name.startswith(alias) or name.endswith(alias)
    return alias in name


def load_specs(raw: str | None) -> dict[str, str]:
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return clean_stored(data)


def clean_stored(data: dict) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in data.items():
        text = str(value or "").strip()
        if text:
            output[str(key)] = text
    return output


def dump_specs(specs: dict[str, str]) -> str:
    return json.dumps(specs, ensure_ascii=False, sort_keys=True)
