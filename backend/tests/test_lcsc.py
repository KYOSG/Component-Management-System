from app.services.lcsc import fetch_lcsc, map_product, search_to_detail
from app.services.specs import default_catalog


def test_map_product_fields():
    mapped = map_product(
        {
            "productCode": "C105580",
            "productModel": "RC0603FR-075K1L",
            "productNameEn": "RES 5.1kΩ ±1% 100mW 0603",
            "brandNameEn": "YAGEO",
            "encapStandard": "0603",
            "parentCatalogName": "Resistors",
            "catalogName": "Chip Resistor - Surface Mount",
            "pdfUrl": "https://datasheet.example/c105580.pdf",
            "productImages": ["https://assets.example/front.jpg"],
            "stockNumber": 100,
            "productPriceList": [{"productPrice": "0.0021", "currencySymbol": "$"}],
            "paramVOList": [
                {"paramName": "阻值", "paramValue": "5.1kΩ"},
                {"paramName": "功率", "paramValue": "100mW"},
            ],
        },
        default_catalog(),
    )
    assert mapped["mpn"] == "RC0603FR-075K1L"
    assert mapped["brand"] == "YAGEO"
    assert mapped["footprint"] == "0603"
    assert mapped["category"] == "电阻"
    assert mapped["value"] == "5.1kΩ"
    assert "功率: 100mW" in mapped["params"]
    assert mapped["mall_stock"] == 100
    assert mapped["mall_price"] == "$0.0021"
    assert mapped["unit_price"] == 0.0021


def test_map_inductor_specs():
    mapped = map_product(
        {
            "productCode": "C19193224",
            "productModel": "CKST141208-0.47uH/M",
            "parentCatalogName": "Inductors, Coils, Chokes",
            "catalogName": "Fixed Inductors",
            "paramVOList": [
                {"paramName": "额定电流", "paramNameEn": "Current Rating", "paramValue": "3A"},
                {"paramName": "电感值", "paramNameEn": "Inductance", "paramValue": "470nH"},
                {"paramName": "精度", "paramNameEn": "Tolerance", "paramValue": "±20%"},
                {"paramName": "饱和电流(Isat)", "paramNameEn": "Current - Saturation(Isat)", "paramValue": "4.5A"},
                {"paramName": "直流电阻(DCR)", "paramNameEn": "DC Resistance(DCR)", "paramValue": "39mΩ"},
            ],
        },
        default_catalog(),
    )
    assert mapped["category"] == "电感"
    assert mapped["value"] == "470nH"
    assert mapped["specs"] == {"irms": "3A", "isat": "4.5A", "dcr": "39mΩ"}


def test_category_uses_last_catalog_level():
    mapped = map_product(
        {
            "productCode": "C82942",
            "productModel": "ME6211C33M5G-N",
            "parentCatalogName": "Power Management (PMIC)",
            "catalogName": "线性稳压器(LDO)",
        },
        default_catalog(),
    )
    assert mapped["category"] == "线性稳压器(LDO)"


def test_search_hit_keeps_last_level_and_params():
    detail = search_to_detail(
        {
            "code": "C5120915",
            "name": "1206 5mΩ ±1% 1W",
            "catalogName": "电流采样电阻/分流器",
            "brandName": "NCT(利昇达)",
            "standard": "1206",
            "model": "LRAM12CFTR005",
            "stockNumber": "1383",
            "image": "https://alimg.example/a.jpg<$>https://alimg.example/b.jpg",
            "priceList": [{"startNumber": 20, "price": 0.1823}],
            "pdfFileUrl": "/upload/public/pdf/source/a.pdf",
        },
        {
            "catalogName": "Voltage Regulators",
            "paramVOList": [{"paramName": "阻值", "paramValue": "5mΩ"}],
        },
    )
    mapped = map_product(detail, default_catalog())
    assert mapped["lcsc_code"] == "C5120915"
    assert mapped["mpn"] == "LRAM12CFTR005"
    assert mapped["category"] == "电阻"
    assert mapped["value"] == "5mΩ"
    assert mapped["mall_stock"] == 1383
    assert mapped["mall_price"] == "¥0.1823"
    assert mapped["datasheet_url"] == "https://atta.szlcsc.com/upload/public/pdf/source/a.pdf"
    assert mapped["image_url"] == "https://alimg.example/a.jpg"
    assert detail["catalogName"] == "电流采样电阻/分流器"


def test_live_c105580():
    info = fetch_lcsc("C105580", default_catalog())
    assert info["mpn"] == "RC0603FR-075K1L"
    assert info["brand"].startswith("YAGEO")
    assert info["footprint"] == "0603"
    assert "5.1k" in info["value"] or "5.1k" in info["params"]
