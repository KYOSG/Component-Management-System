import pytest

from app.services.specs import (
    CatalogCategory,
    SpecCatalog,
    SpecField,
    SpecValidationError,
    default_catalog,
)


def test_inductor_prefers_temperature_rise_name():
    specs = default_catalog().extract(
        "电感",
        [
            ("额定电流", "1A"),
            ("温升电流(Irms)", "1.2A"),
            ("饱和电流(Isat)", "2A"),
            ("直流电阻(DCR)", "10mΩ"),
            ("精度", "±20%"),
        ],
    )
    assert specs == {"irms": "1.2A", "isat": "2A", "dcr": "10mΩ"}


def test_present_specs_fills_missing_inductor_fields():
    shown = default_catalog().present(
        "电感",
        {"isat": "2A", "tolerance": "±20%"},
        "电感值: 10uH；额定电流: 1.5A；饱和电流(Isat): 3A；直流电阻(DCR): 80mΩ",
    )
    assert shown == {"irms": "1.5A", "isat": "2A", "dcr": "80mΩ"}


def test_present_fills_any_category_from_params():
    shown = default_catalog().present("电阻", {}, "阻值: 10kΩ；精度: ±1%；功率: 100mW")
    assert shown == {"tolerance": "±1%", "power": "100mW"}


def test_present_keeps_value_outside_current_options():
    catalog = SpecCatalog(
        [
            CatalogCategory(
                name="电阻",
                lcsc_keywords=("resistor",),
                fields=(
                    SpecField(
                        key="tolerance",
                        label="精度",
                        type="select",
                        options=("a", "b", "c"),
                        aliases=("精度",),
                    ),
                ),
            )
        ]
    )
    shown = catalog.present("电阻", {"tolerance": "±1%"}, "精度: ±5%")
    assert shown == {"tolerance": "±1%"}


def test_clean_checks_number_select_and_required():
    catalog = SpecCatalog(
        [
            CatalogCategory(
                name="MOS",
                lcsc_keywords=("mosfet",),
                fields=(
                    SpecField(key="vds", label="漏源耐压", type="number", unit="V", required=True, aliases=("漏源耐压",)),
                    SpecField(key="pkg", label="封装类型", type="select", options=("贴片", "插件"), aliases=("封装类型",)),
                ),
            )
        ]
    )
    assert catalog.clean("MOS", {"vds": "30V", "pkg": "贴片", "extra": "x"}, strict=True) == {"vds": "30", "pkg": "贴片"}
    assert catalog.clean("MOS", {"vds": "abc", "pkg": "没有"}, strict=False) == {}
    with pytest.raises(SpecValidationError, match="漏源耐压需要是数字"):
        catalog.clean("MOS", {"vds": "abc", "pkg": "贴片"}, strict=True)
    with pytest.raises(SpecValidationError, match="请填写漏源耐压"):
        catalog.clean("MOS", {"pkg": "贴片"}, strict=True)
    with pytest.raises(SpecValidationError, match="封装类型不在可选项内"):
        catalog.clean("MOS", {"vds": "30", "pkg": "没有"}, strict=True)
    assert catalog.extract("MOS", [("漏源耐压", "60V")]) == {"vds": "60"}
