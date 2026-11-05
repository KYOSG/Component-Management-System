from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FIELD_KEY = re.compile(r"^[a-z0-9_]{1,32}$")
_FIELD_TYPES = {"text", "number", "select"}


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _specs_dict(value) -> dict[str, str]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    output: dict[str, str] = {}
    for key, item in value.items():
        text = str(item or "").strip()
        if text:
            output[str(key)] = text
    return output


class AuthIn(BaseModel):
    email: str
    password: str


class UserOut(ORMModel):
    id: int
    email: str
    is_admin: bool
    must_change_password: bool = False
    created_at: datetime


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


class AuthOptionsOut(BaseModel):
    allow_register: bool


class UserWrite(BaseModel):
    email: str
    password: str = ""
    is_admin: bool = False


class BoxIn(BaseModel):
    name: str
    box_type: str = "grid"
    rows: int = 0
    cols: int = 0
    slot_count: int = 0
    remark: str = ""

    @field_validator("box_type")
    @classmethod
    def box_type_name(cls, value: str) -> str:
        text = (value or "grid").strip()
        if text not in {"grid", "reel"}:
            raise ValueError("物料盒类型只能是 grid 或 reel")
        return text


class BoxOut(ORMModel):
    id: int
    name: str
    box_type: str = "grid"
    rows: int
    cols: int
    slot_count: int = 0
    remark: str
    created_at: datetime


class ItemIn(BaseModel):
    lcsc_code: str | None = None
    mpn: str = ""
    name: str = ""
    brand: str = ""
    footprint: str = ""
    category: str = ""
    value: str = ""
    params: str = ""
    specs: dict[str, str] = Field(default_factory=dict)
    quantity: int = 0
    min_stock: int = 0
    unit_price: float | None = None
    datasheet_url: str = ""
    image_url: str = ""
    remark: str = ""

    @field_validator("min_stock")
    @classmethod
    def min_stock_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("低库存阈值不能小于 0")
        return value

    @field_validator("quantity")
    @classmethod
    def quantity_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("库存不能为负数")
        return value

    @field_validator("unit_price")
    @classmethod
    def price_non_negative(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("单价不能为负数")
        return value

    @field_validator("specs", mode="before")
    @classmethod
    def specs_as_dict(cls, value):
        return _specs_dict(value)


class LocationOut(BaseModel):
    id: int
    item_id: int
    location_type: str
    box_id: int | None = None
    box_name: str | None = None
    row: int | None = None
    col: int | None = None
    reel_label: str = ""
    slot_index: int | None = None
    quantity: int


class LocationIn(BaseModel):
    location_type: str
    box_id: int | None = None
    row: int | None = None
    col: int | None = None
    reel_label: str = ""
    slot_index: int | None = None
    quantity: int = 0

    @field_validator("quantity")
    @classmethod
    def quantity_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("数量不能为负数")
        return value


class LocationUpdate(BaseModel):
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("数量不能为负数")
        return value


class TransferIn(BaseModel):
    from_location_id: int
    to_type: str
    to_box_id: int | None = None
    to_row: int | None = None
    to_col: int | None = None
    to_reel_label: str = ""
    to_slot_index: int | None = None
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("流转数量需要大于 0")
        return value


class ItemCheckoutIn(BaseModel):
    location_id: int
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("出库数量需要大于 0")
        return value


class ItemOut(BaseModel):
    id: int
    lcsc_code: str | None = None
    mpn: str
    name: str
    brand: str
    footprint: str
    category: str
    value: str
    params: str
    specs: dict[str, str] = Field(default_factory=dict)
    quantity: int
    min_stock: int = 0
    low_stock: bool = False
    unit_price: float | None = None
    total_value: float | None = None
    locations: list[LocationOut] = Field(default_factory=list)
    datasheet_url: str
    image_url: str
    remark: str
    lcsc_sync_status: str = "idle"
    lcsc_sync_error: str = ""
    created_at: datetime
    updated_at: datetime


class SearchHint(BaseModel):
    kind: str
    label: str


class ItemPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ItemOut]
    hints: list[SearchHint] = Field(default_factory=list)
    low_stock_count: int = 0


class CellOut(BaseModel):
    row: int
    col: int
    item: ItemOut | None = None
    location_id: int | None = None
    location_quantity: int = 0
    cell_value: float | None = None
    dimmed: bool = False


class ReelSlotOut(BaseModel):
    slot_index: int
    location_id: int | None = None
    reel_label: str = ""
    quantity: int = 0
    cell_value: float | None = None
    dimmed: bool = False
    item: ItemOut | None = None


class PlacedItemOut(ItemOut):
    location_id: int
    location_quantity: int
    cell_value: float | None = None
    reel_label: str = ""


class BoxMapOut(BaseModel):
    id: int
    name: str
    box_type: str = "grid"
    rows: int
    cols: int
    slot_count: int = 0
    remark: str
    cells: list[CellOut]
    reel_slots: list[ReelSlotOut] = Field(default_factory=list)
    invalid_items: list[ItemOut]


class MapStats(BaseModel):
    item_count: int
    box_count: int
    quantity_total: int
    total_value: float = 0
    low_stock_count: int = 0


class MapOut(BaseModel):
    stats: MapStats
    categories: list[str]
    boxes: list[BoxMapOut]
    unboxed: list[PlacedItemOut]
    highlights: dict[str, list[str]]


class StatPoint(BaseModel):
    date: str
    value: float


class StatSeries(BaseModel):
    start: str
    end: str
    points: list[StatPoint]


class ProjectBrief(BaseModel):
    id: int
    name: str
    source_filename: str
    format: str
    purchase_sets: int
    order_no: str
    imported_at: datetime
    line_count: int


class LineOut(BaseModel):
    id: int
    line_no: int
    designators: str
    quantity_per_board: int
    quantity_required: int
    lcsc_code: str
    mpn: str
    brand: str
    footprint: str
    value: str
    params: str
    product_name: str
    category: str
    match_status: str
    matched_item_id: int | None = None
    reason: str = ""
    risks: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    stock: int | None = None
    matched_at: datetime | None = None


class ProjectUpdate(BaseModel):
    purchase_sets: int

    @field_validator("purchase_sets")
    @classmethod
    def purchase_sets_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("采购套数至少为 1")
        return value


class ProjectOut(ProjectBrief):
    ai_enabled: bool
    lines: list[LineOut]


class SystemSettingsIn(BaseModel):
    database_location: str = ""
    database_name: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""
    allow_register: bool | None = None


class SystemSettingsOut(BaseModel):
    database_location: str
    database_name: str
    deepseek_api_key: str
    deepseek_api_key_set: bool = False
    deepseek_base_url: str
    deepseek_model: str
    allow_register: bool = False
    database_switched: bool = False


class AiTestIn(BaseModel):
    prompt: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""


class AiTestOut(BaseModel):
    output: str


class StockDeltaIn(BaseModel):
    delta: int


class ReplaceIn(BaseModel):
    item_id: int | None = None
    lcsc_code: str = ""


class LcscCreateIn(BaseModel):
    lcsc_code: str


class BulkAddOut(BaseModel):
    added: int
    incremented: int


class CheckoutOut(BaseModel):
    deducted: int
    skipped: int


class AdoptOut(BaseModel):
    lcsc_code: str | None = None
    mpn: str = ""
    name: str = ""
    brand: str = ""
    footprint: str = ""
    category: str = ""
    value: str = ""
    params: str = ""
    specs: dict[str, str] = Field(default_factory=dict)
    datasheet_url: str = ""
    image_url: str = ""
    quantity: int = 0
    unit_price: float | None = None
    remark: str = ""
    mall_stock: int | None = None
    mall_price: str = ""
    warning: str = ""


def _text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[,，]", value)
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in output:
            output.append(text)
    return output


class SpecFieldIn(BaseModel):
    key: str
    label: str
    type: str = "text"
    unit: str = ""
    options: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    required: bool = False

    @field_validator("key")
    @classmethod
    def key_format(cls, value: str) -> str:
        text = value.strip().lower()
        if _FIELD_KEY.fullmatch(text) is None:
            raise ValueError("字段键名只能使用小写字母、数字和下划线，最长 32 位")
        return text

    @field_validator("label")
    @classmethod
    def label_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("请填写字段显示名")
        if len(text) > 64:
            raise ValueError("字段显示名过长")
        return text

    @field_validator("type")
    @classmethod
    def type_name(cls, value: str) -> str:
        text = (value or "text").strip()
        if text not in _FIELD_TYPES:
            raise ValueError("字段类型只能是 text、number 或 select")
        return text

    @field_validator("unit")
    @classmethod
    def unit_text(cls, value: str) -> str:
        text = (value or "").strip()
        if len(text) > 16:
            raise ValueError("单位过长")
        return text

    @field_validator("options", "aliases", mode="before")
    @classmethod
    def as_text_list(cls, value):
        return _text_list(value)

    @model_validator(mode="after")
    def check_field(self):
        if self.type == "select" and not self.options:
            raise ValueError("字典字段需要至少一个选项")
        if not self.aliases:
            self.aliases = [self.label]
        return self


class SpecCategoryIn(BaseModel):
    name: str
    lcsc_keywords: list[str] = Field(default_factory=list)
    fields: list[SpecFieldIn] = Field(default_factory=list)
    sort_order: int | None = None

    @field_validator("name")
    @classmethod
    def name_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("请填写类目名称")
        if len(text) > 120:
            raise ValueError("类目名称过长")
        return text

    @field_validator("lcsc_keywords", mode="before")
    @classmethod
    def keyword_list(cls, value):
        return _text_list(value)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("同一类目的字段键名不能重复")
        return self


class SpecFieldOut(BaseModel):
    key: str
    label: str
    type: str
    unit: str = ""
    options: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    required: bool = False


class SpecCategoryOut(BaseModel):
    id: int
    name: str
    lcsc_keywords: list[str]
    fields: list[SpecFieldOut]
    sort_order: int
    created_at: datetime
    updated_at: datetime


class OrderLineIn(BaseModel):
    lcsc_code: str = Field(default="", max_length=64)
    mpn: str = Field(default="", max_length=255)
    name: str = Field(default="", max_length=255)
    brand: str = Field(default="", max_length=255)
    footprint: str = Field(default="", max_length=255)
    ship_qty: int = 0
    unit_price: float | None = None
    skip: bool = False

    @field_validator("lcsc_code", "mpn", "name", "brand", "footprint")
    @classmethod
    def strip_order_text(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("ship_qty")
    @classmethod
    def ship_qty_range(cls, value: int) -> int:
        if value < 0 or value > 10_000_000:
            raise ValueError("发货数量不正确")
        return value

    @field_validator("unit_price")
    @classmethod
    def unit_price_range(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0 or value > 1_000_000:
            raise ValueError("单价不正确")
        return round(float(value), 6)


class OrderCommitIn(BaseModel):
    order_no: str = ""
    lines: list[OrderLineIn] = Field(default_factory=list, max_length=2000)
    refresh_codes: list[str] = Field(default_factory=list, max_length=2000)

    @field_validator("order_no")
    @classmethod
    def order_no_text(cls, value: str) -> str:
        return (value or "").strip()[:128]

    @field_validator("refresh_codes")
    @classmethod
    def refresh_codes_text(cls, value: list[str]) -> list[str]:
        output: list[str] = []
        for item in value:
            text = str(item or "").strip().upper()[:64]
            if text and text not in output:
                output.append(text)
        return output


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    unit_price: float | None = None
    skip: bool
    skip_reason: str = ""
    action: str
    current_quantity: int = 0


class OrderPreviewOut(BaseModel):
    order_no: str
    ordered_at: str
    lines: list[OrderLineOut]
    create_count: int
    stock_count: int
    skip_count: int
    ship_total: int
    already_imported: bool = False


class OrderCommitOut(BaseModel):
    created: int
    stocked: int
    skipped: int
    ship_total: int
    refresh_queued: int = 0


class LcscRefreshIn(BaseModel):
    item_ids: list[int] = Field(default_factory=list, max_length=20000)
    lcsc_codes: list[str] = Field(default_factory=list, max_length=2000)
    all: bool = False

    @field_validator("lcsc_codes")
    @classmethod
    def codes_text(cls, value: list[str]) -> list[str]:
        output: list[str] = []
        for item in value:
            text = str(item or "").strip().upper()[:64]
            if text and text not in output:
                output.append(text)
        return output

    @model_validator(mode="after")
    def one_target(self):
        chosen = int(bool(self.item_ids)) + int(bool(self.lcsc_codes)) + int(self.all)
        if chosen != 1:
            raise ValueError("请指定要更新的物料")
        return self


class LcscRefreshOut(BaseModel):
    queued: int
    skipped_busy: int = 0
    skipped_no_code: int = 0
    pending_codes: list[str] = Field(default_factory=list)
    queued_codes: list[str] = Field(default_factory=list)


class LcscRefreshStatusOut(BaseModel):
    queued: int = 0
    running: int = 0
    failed: int = 0
