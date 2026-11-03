from __future__ import annotations

import httpx

from app.services.specs import SpecCatalog


class LcscError(Exception):
    pass


VALUE_NAMES = {"阻值", "容值", "电感量", "电感值", "resistance", "capacitance", "inductance"}
SEARCH_URL = "https://lceda.cn/api/eda/product/search"
DETAIL_URL = "https://wmsc.lcsc.com/ftps/wm/product/detail"
PDF_HOST = "https://atta.szlcsc.com"


def map_product(result: dict, catalog: SpecCatalog) -> dict:
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
    category = catalog.map_category(result.get("catalogName") or "")
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
        "specs": catalog.extract(category, pairs),
        "datasheet_url": result.get("pdfUrl") or "",
        "image_url": image_url,
        "mall_stock": result.get("stockNumber"),
        "mall_price": mall_price,
        "unit_price": _highest_price(prices),
    }


def _highest_price(prices) -> float | None:
    best: float | None = None
    for row in prices or []:
        if not isinstance(row, dict):
            continue
        try:
            number = round(float(row.get("productPrice")), 6)
        except (TypeError, ValueError):
            continue
        if best is None or number > best:
            best = number
    return best

def search_to_detail(item: dict, detail: dict | None) -> dict:
    images = [_absolute_url(part) for part in str(item.get("image") or "").split("<$>")]
    images = [url for url in images if url]
    prices = item.get("priceList") or []
    price_list = []
    if prices and isinstance(prices[0], dict) and prices[0].get("price") not in (None, ""):
        price_list = [{"productPrice": prices[0]["price"], "currencySymbol": "¥"}]
    catalog_name = (item.get("catalogName") or "").strip()
    if not catalog_name and isinstance(detail, dict):
        catalog_name = (detail.get("catalogName") or "").strip()
    return {
        "productCode": item.get("code") or "",
        "productModel": item.get("model") or "",
        "productNameEn": item.get("name") or "",
        "brandNameEn": item.get("brandName") or "",
        "encapStandard": item.get("standard") or "",
        "catalogName": catalog_name,
        "pdfUrl": _absolute_url(item.get("pdfFileUrl") or ""),
        "productImages": images[:1],
        "stockNumber": _stock(item.get("stockNumber")),
        "productPriceList": price_list,
        "paramVOList": _param_list(item, detail),
    }


def fetch_lcsc(code: str, catalog: SpecCatalog, *, user_id: int | None = None) -> dict:
    product_code = (code or "").strip().upper()
    if not product_code:
        raise LcscError("查询失败，请手填")
    try:
        with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            searched = _search_product(client, product_code)
            detail = _fetch_detail(client, product_code)
    except Exception as exc:
        raise LcscError("查询失败，请手填") from exc
    if searched:
        result = search_to_detail(searched, detail)
    elif detail:
        result = detail
    else:
        raise LcscError("查询失败，请手填")
    mapped = map_product(result, catalog)
    mapped["lcsc_code"] = (mapped["lcsc_code"] or product_code).strip().upper()
    from app.services.images import localize, safe_stem

    code = safe_stem(mapped["lcsc_code"])
    remote = mapped.get("image_url") or ""
    if remote and code and user_id is not None:
        mapped["image_url"] = localize(remote, f"lcsc-{code}", user_id)
    else:
        mapped["image_url"] = ""
    return mapped


def _search_product(client: httpx.Client, product_code: str) -> dict | None:
    payload = _read_json(client, SEARCH_URL, {"keyword": product_code, "page": 1, "pageSize": 10})
    result = payload.get("result") if isinstance(payload, dict) else None
    items = result.get("productList") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return None
    wanted = product_code.upper()
    for item in items:
        if isinstance(item, dict) and str(item.get("code") or "").upper() == wanted:
            return item
    return None


def _fetch_detail(client: httpx.Client, product_code: str) -> dict | None:
    payload = _read_json(client, DETAIL_URL, {"productCode": product_code})
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, dict) and result.get("productCode"):
        return result
    return None


def _read_json(client: httpx.Client, url: str, params: dict) -> dict | None:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _param_list(item: dict, detail: dict | None) -> list:
    if isinstance(detail, dict) and detail.get("paramVOList"):
        return detail["paramVOList"]
    raw = item.get("productParams")
    if not isinstance(raw, list):
        return []
    output = []
    for param in raw:
        if not isinstance(param, dict):
            continue
        name = param.get("paramName") or param.get("parameterName") or ""
        value = param.get("paramValue") or param.get("parameterValue") or param.get("parameterDetailValue") or ""
        name = str(name).strip()
        value = str(value).strip()
        if name and value:
            output.append({"paramName": name, "paramValue": value})
    return output


def _absolute_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("/"):
        return f"{PDF_HOST}{text}"
    return ""


def _stock(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return value
