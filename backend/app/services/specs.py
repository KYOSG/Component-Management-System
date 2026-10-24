from __future__ import annotations

import json
import re

# key, 显示名, 立创/BOM 参数名别名。匹配前会去掉空格和标点并转小写。
SPEC_FIELDS: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
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
        ("isat", "饱和电流", ("饱和电流", "saturation current", "isat")),
        ("tolerance", "精度", ("精度", "公差", "tolerance", "inductance tolerance")),
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


def extract_specs(category: str, pairs: list[tuple[str, str]]) -> dict[str, str]:
    fields = SPEC_FIELDS.get((category or "").strip())
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
    for key, _label, aliases in fields:
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
            output[key] = found
    return output


def specs_from_params(category: str, params: str) -> dict[str, str]:
    return extract_specs(category, parse_params(params))


def clean_specs(category: str, specs: dict | None) -> dict[str, str]:
    allowed = {key for key, _label, _aliases in SPEC_FIELDS.get((category or "").strip(), [])}
    output: dict[str, str] = {}
    for key, value in (specs or {}).items():
        if key not in allowed:
            continue
        text = str(value or "").strip()
        if text:
            output[key] = text
    return output


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
