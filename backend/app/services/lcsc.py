from __future__ import annotations

import httpx

from app.services.specs import extract_specs


class LcscError(Exception):
    pass


CATEGORY_RULES = (
    ("电阻", ("resistor", "电阻")),
    ("电容", ("capacitor", "电容")),
    ("电感", ("inductor", "电感")),
    ("二极管", ("diode", "二极管")),
    ("MOS", ("mosfet", "mos管", "mos")),
    ("三极管", ("transistor", "三极管")),
    ("连接器", ("connector", "连接器")),
    ("电源", ("power management", "电源")),
)

VALUE_NAMES = {"阻值", "容值", "电感量", "电感值", "resistance", "capacitance", "inductance"}


def map_category(parent: str, catalog: str) -> str:
    blob = f"{parent} {catalog}".lower()
    for label, keys in CATEGORY_RULES:
        if any(key.lower() in blob for key in keys):
            return label
    return catalog or parent or ""


def map_product(result: dict) -> dict:
    parts: list[str] = []
    pairs: list[tuple[str, str]] = []
    value = ""
    for param in result.get("paramVOList") or []:
        name = (param.get("paramName") or param.get("paramNameEn") or "").strip()
        param_value = (param.get("paramValue") or param.get("paramValueEn") or "").strip()
        if name and param_value:
            parts.append(f"{name}: {param_value}")
            pairs.append((name, param_value))
        if name.lower() in VALUE_NAMES and param_value:
            value = param_value
    category = map_category(result.get("parentCatalogName") or "", result.get("catalogName") or "")
    images = result.get("productImages") or []
    image_url = images[0] if images and isinstance(images[0], str) else ""
    prices = result.get("productPriceList") or []
    mall_price = ""
    if prices and isinstance(prices[0], dict) and prices[0].get("productPrice"):
        symbol = prices[0].get("currencySymbol") or ""
        mall_price = f"{symbol}{prices[0]['productPrice']}"
    return {
        "lcsc_code": result.get("productCode") or "",
        "mpn": result.get("productModel") or "",
        "name": result.get("productNameEn") or result.get("productIntroEn") or "",
        "brand": result.get("brandNameEn") or "",
        "footprint": result.get("encapStandard") or "",
        "category": category,
        "value": value,
        "params": "；".join(parts),
        "specs": extract_specs(category, pairs),
        "datasheet_url": result.get("pdfUrl") or "",
        "image_url": image_url,
        "mall_stock": result.get("stockNumber"),
        "mall_price": mall_price,
    }


def fetch_lcsc(code: str) -> dict:
    product_code = (code or "").strip()
    if not product_code:
        raise LcscError("查询失败，请手填")
    url = f"https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={product_code}"
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise LcscError("查询失败，请手填") from exc
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not result.get("productCode"):
        raise LcscError("查询失败，请手填")
    mapped = map_product(result)
    mapped["lcsc_code"] = mapped["lcsc_code"] or product_code
    return mapped
