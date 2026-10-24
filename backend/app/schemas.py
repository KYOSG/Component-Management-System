from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthIn(BaseModel):
    email: str
    password: str


class UserOut(ORMModel):
    id: int
    email: str
    is_admin: bool
    created_at: datetime


class UserWrite(BaseModel):
    email: str
    password: str = ""
    is_admin: bool = False


class BoxIn(BaseModel):
    name: str
    rows: int
    cols: int
    remark: str = ""


class BoxOut(ORMModel):
    id: int
    name: str
    rows: int
    cols: int
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
    quantity: int = 0
    box_id: int | None = None
    row: int | None = None
    col: int | None = None
    datasheet_url: str = ""
    image_url: str = ""
    remark: str = ""

    @field_validator("quantity")
    @classmethod
    def quantity_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("库存不能为负数")
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
    quantity: int
    box_id: int | None = None
    box_name: str | None = None
    row: int | None = None
    col: int | None = None
    datasheet_url: str
    image_url: str
    remark: str
    created_at: datetime
    updated_at: datetime


class ItemPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ItemOut]


class CellOut(BaseModel):
    row: int
    col: int
    item: ItemOut | None = None
    dimmed: bool = False


class BoxMapOut(BaseModel):
    id: int
    name: str
    rows: int
    cols: int
    remark: str
    cells: list[CellOut]
    invalid_items: list[ItemOut]


class MapStats(BaseModel):
    item_count: int
    box_count: int
    quantity_total: int


class MapOut(BaseModel):
    stats: MapStats
    categories: list[str]
    boxes: list[BoxMapOut]
    unboxed: list[ItemOut]
    highlights: dict[str, list[str]]


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


class ProjectOut(ProjectBrief):
    ai_enabled: bool
    lines: list[LineOut]


class AdoptOut(BaseModel):
    lcsc_code: str | None = None
    mpn: str = ""
    name: str = ""
    brand: str = ""
    footprint: str = ""
    category: str = ""
    value: str = ""
    params: str = ""
    datasheet_url: str = ""
    image_url: str = ""
    quantity: int = 0
    box_id: int | None = None
    row: int | None = None
    col: int | None = None
    remark: str = ""
    mall_stock: int | None = None
    mall_price: str = ""
    warning: str = ""
