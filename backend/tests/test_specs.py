from app.services.specs import extract_specs, present_specs


def test_inductor_prefers_temperature_rise_name():
    specs = extract_specs(
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
    shown = present_specs(
        "电感",
        {"isat": "2A", "tolerance": "±20%"},
        "电感值: 10uH；额定电流: 1.5A；饱和电流(Isat): 3A；直流电阻(DCR): 80mΩ",
    )
    assert shown == {"irms": "1.5A", "isat": "2A", "dcr": "80mΩ"}
