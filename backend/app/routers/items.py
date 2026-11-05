from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Item, ItemLocation, ProjectLine, User, utcnow
from app.schemas import (
    ItemCheckoutIn,
    ItemIn,
    ItemOut,
    ItemPage,
    LcscCreateIn,
    LcscRefreshIn,
    LcscRefreshOut,
    LcscRefreshStatusOut,
    LocationOut,
    OrderCommitIn,
    OrderCommitOut,
    OrderLineOut,
    OrderPreviewOut,
    SearchHint,
)
from app.services.images import assign_image, delete_item_image, display_image_url
from app.services.lcsc import LcscError, fetch_lcsc
from app.services.lcsc_refresh import BUSY_DETAIL, kick_refresh, queue_items, refresh_counts
from app.services.order_import import OrderError, already_imported, apply_order, build_preview, parse_order
from app.services.search import item_view, plan_query
from app.services.spec_config import load_catalog
from app.services.specs import SpecCatalog, SpecValidationError, dump_specs, load_specs
from app.services.stock import (
    StockError,
    checkout_location,
    is_low_stock,
    line_value,
    location_views,
    set_total_quantity,
    unbox_item,
)

router = APIRouter(prefix="/api/items", tags=["items"])

LOW_STOCK = and_(Item.min_stock > 0, Item.quantity < Item.min_stock)
EXPORT_HEADERS = (
    "立创编号", "厂家型号", "商品名称", "品牌", "封装", "类目", "值", "规格", "参数",
    "库存", "低库存阈值", "低库存", "单价", "金额", "存放位置", "手册", "备注", "更新时间",
)


def clean_code(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    return text or None


def raise_stock(exc: StockError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def item_out(item: Item, catalog: SpecCatalog, locations) -> ItemOut:
    price = item.unit_price
    return ItemOut(
        id=item.id,
        lcsc_code=item.lcsc_code,
        mpn=item.mpn or "",
        name=item.name or "",
        brand=item.brand or "",
        footprint=item.footprint or "",
        category=item.category or "",
        value=item.value or "",
        params=item.params or "",
        specs=catalog.present(item.category or "", load_specs(item.specs), item.params or ""),
        quantity=item.quantity or 0,
        min_stock=item.min_stock or 0,
        low_stock=is_low_stock(item),
        unit_price=price,
        total_value=line_value(item.quantity or 0, price),
        locations=locations,
        datasheet_url=item.datasheet_url or "",
        image_url=display_image_url(item.image_url or "", item.user_id),
        remark=item.remark or "",
        lcsc_sync_status=item.lcsc_sync_status or "idle",
        lcsc_sync_error=item.lcsc_sync_error or "",
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def present_items(db: Session, items: list[Item], catalog: SpecCatalog) -> list[ItemOut]:
    views = location_views(db, [item.id for item in items])
    return [item_out(item, catalog, views.get(item.id, [])) for item in items]


def present_item(db: Session, item: Item, catalog: SpecCatalog) -> ItemOut:
    return present_items(db, [item], catalog)[0]


def apply_fields(db: Session, user: User, item: Item, data: ItemIn, catalog: SpecCatalog) -> None:
    code = clean_code(data.lcsc_code)
    if code:
        taken = db.scalar(
            select(Item.id).where(
                Item.user_id == user.id,
                Item.lcsc_code == code,
                Item.id != (item.id or 0),
            )
        )
        if taken:
            raise HTTPException(status_code=400, detail="立创编号已存在")
    item.lcsc_code = code
    item.mpn = data.mpn.strip()
    item.name = data.name.strip()
    item.brand = data.brand.strip()
    item.footprint = data.footprint.strip()
    item.category = data.category.strip()
    item.value = data.value.strip()
    item.params = data.params.strip()
    try:
        item.specs = dump_specs(catalog.clean(item.category, data.specs, strict=True))
    except SpecValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item.min_stock = data.min_stock
    item.unit_price = data.unit_price
    item.datasheet_url = data.datasheet_url.strip()
    item.remark = data.remark.strip()
    item.lcsc_sync_status = "idle"
    item.lcsc_sync_error = ""
    item.updated_at = utcnow()


def contains(column, text: str):
    escaped = text.replace("\\", "\\\\").replace("%", "\%").replace("_", "\_")
    return column.like(f"%{escaped}%", escape="\\")


def _field_filters(user: User, fields: dict[str, str], low_stock: bool) -> list:
    filters = [Item.user_id == user.id]
    for column, key in (
        (Item.lcsc_code, "lcsc_code"),
        (Item.mpn, "mpn"),
        (Item.name, "name"),
        (Item.footprint, "footprint"),
        (Item.category, "category"),
        (Item.remark, "remark"),
    ):
        text = (fields.get(key) or "").strip()
        if text:
            filters.append(contains(column, text))
    if low_stock:
        filters.append(LOW_STOCK)
    return filters


def find_items(
    db: Session,
    user: User,
    catalog: SpecCatalog,
    q: str,
    fields: dict[str, str],
    low_stock: bool,
) -> tuple[list[Item], list[SearchHint]]:
    filters = _field_filters(user, fields, low_stock)
    rows = list(db.scalars(select(Item).where(*filters).order_by(Item.id.desc())).all())
    plan = plan_query(q, [category.name for category in catalog.categories])
    if not plan:
        return rows, []
    hits = [item for item in rows if plan.matches(item_view(item, load_specs(item.specs)))]
    return hits, [SearchHint(**hint) for hint in plan.hints()]


def low_stock_count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Item).where(Item.user_id == user_id, LOW_STOCK)) or 0


@router.get("", response_model=ItemPage)
def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str = "",
    lcsc_code: str = "",
    mpn: str = "",
    name: str = "",
    footprint: str = "",
    category: str = "",
    remark: str = "",
    low_stock: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemPage:
    catalog = load_catalog(db, user.id)
    fields = {"lcsc_code": lcsc_code, "mpn": mpn, "name": name, "footprint": footprint, "category": category, "remark": remark}
    rows, hints = find_items(db, user, catalog, q, fields, low_stock)
    start = (page - 1) * page_size
    return ItemPage(
        total=len(rows),
        page=page,
        page_size=page_size,
        items=present_items(db, rows[start : start + page_size], catalog),
        hints=hints,
        low_stock_count=low_stock_count(db, user.id),
    )


def _place_label(place: LocationOut) -> str:
    if place.location_type == "unboxed":
        where = "未入盒"
    elif place.location_type == "tape_reel":
        where = f"{place.box_name or '料卷盒'} {place.reel_label or place.slot_index or ''}".strip()
    else:
        where = f"{place.box_name or '物料盒'} {place.row}-{place.col}"
    return f"{where} ×{place.quantity}"


def _spec_text(catalog: SpecCatalog, item: Item, shown: dict[str, str]) -> str:
    labels = {field.key: field.label for field in catalog.fields_for(item.category or "")}
    return "；".join(f"{labels.get(key, key)}: {value}" for key, value in shown.items())


def _safe_cell(value):
    # 防止表格把以 = + - @ 开头的文本当成公式执行。
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _export_row(catalog: SpecCatalog, item: Item, places: list[LocationOut]) -> list:
    shown = catalog.present(item.category or "", load_specs(item.specs), item.params or "")
    record = (
        item.lcsc_code or "",
        item.mpn or "",
        item.name or "",
        item.brand or "",
        item.footprint or "",
        item.category or "",
        item.value or "",
        _spec_text(catalog, item, shown),
        item.params or "",
        item.quantity or 0,
        item.min_stock or 0,
        "是" if is_low_stock(item) else "",
        item.unit_price,
        line_value(item.quantity or 0, item.unit_price),
        "；".join(_place_label(place) for place in places),
        item.datasheet_url or "",
        item.remark or "",
        item.updated_at.strftime("%Y-%m-%d %H:%M") if item.updated_at else "",
    )
    return [_safe_cell(value) for value in record]


@router.get("/export")
def export_items(
    q: str = "",
    lcsc_code: str = "",
    mpn: str = "",
    name: str = "",
    footprint: str = "",
    category: str = "",
    remark: str = "",
    low_stock: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    catalog = load_catalog(db, user.id)
    fields = {"lcsc_code": lcsc_code, "mpn": mpn, "name": name, "footprint": footprint, "category": category, "remark": remark}
    rows, _hints = find_items(db, user, catalog, q, fields, low_stock)
    views = location_views(db, [item.id for item in rows])
    book = Workbook()
    sheet = book.active
    sheet.title = "物料库"
    sheet.append(EXPORT_HEADERS)
    for item in rows:
        sheet.append(_export_row(catalog, item, views.get(item.id, [])))
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    book.save(buffer)
    buffer.seek(0)
    filename = f"items-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _upload_bytes(file: UploadFile) -> tuple[str, bytes]:
    filename = Path(file.filename or "").name
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="请上传文件")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 10MB")
    return filename, data


def _preview_response(preview, imported: bool) -> OrderPreviewOut:
    return OrderPreviewOut(
        order_no=preview.order_no,
        ordered_at=preview.ordered_at,
        lines=[OrderLineOut.model_validate(line, from_attributes=True) for line in preview.lines],
        create_count=preview.create_count,
        stock_count=preview.stock_count,
        skip_count=preview.skip_count,
        ship_total=preview.ship_total,
        already_imported=imported,
    )


@router.post("/order-preview", response_model=OrderPreviewOut)
def preview_order(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderPreviewOut:
    filename, data = _upload_bytes(file)
    catalog = load_catalog(db, user.id)
    try:
        parsed = parse_order(filename, data, catalog)
    except OrderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    codes = [line.lcsc_code for line in parsed.lines if line.lcsc_code]
    quantities: dict[str, int] = {}
    if codes:
        rows = db.scalars(select(Item).where(Item.user_id == user.id, Item.lcsc_code.in_(codes))).all()
        quantities = {item.lcsc_code: item.quantity or 0 for item in rows if item.lcsc_code}
    preview = build_preview(parsed, quantities)
    return _preview_response(preview, already_imported(db, user.id, parsed.order_no))


@router.post("/order-commit", response_model=OrderCommitOut)
def commit_order(
    body: OrderCommitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderCommitOut:
    if not body.lines:
        raise HTTPException(status_code=400, detail="没有可入库的发货明细")
    catalog = load_catalog(db, user.id)
    try:
        result = apply_order(db, user.id, catalog, body.order_no, body.lines)
    except OrderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    refresh_queued = 0
    if body.refresh_codes:
        refresh_queued = queue_items(db, user.id, lcsc_codes=body.refresh_codes).queued
    db.commit()
    if refresh_queued:
        kick_refresh()
    return OrderCommitOut(
        created=result.created,
        stocked=result.stocked,
        skipped=result.skipped,
        ship_total=result.ship_total,
        refresh_queued=refresh_queued,
    )


@router.get("/lcsc-refresh/status", response_model=LcscRefreshStatusOut)
def lcsc_refresh_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> LcscRefreshStatusOut:
    return LcscRefreshStatusOut(**refresh_counts(db, user.id))


@router.post("/lcsc-refresh", response_model=LcscRefreshOut)
def lcsc_refresh(
    body: LcscRefreshIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LcscRefreshOut:
    if body.all:
        result = queue_items(db, user.id, all_items=True)
    elif body.item_ids:
        result = queue_items(db, user.id, item_ids=body.item_ids)
    else:
        result = queue_items(db, user.id, lcsc_codes=body.lcsc_codes)
    db.commit()
    if result.queued:
        kick_refresh()
    return LcscRefreshOut(
        queued=result.queued,
        skipped_busy=result.skipped_busy,
        skipped_no_code=result.skipped_no_code,
        pending_codes=result.pending_codes,
        queued_codes=result.queued_codes,
    )


@router.post("/from-lcsc", response_model=ItemOut)
def create_from_lcsc(
    body: LcscCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    code = clean_code(body.lcsc_code)
    if not code:
        raise HTTPException(status_code=400, detail="请填写立创编号")
    catalog = load_catalog(db, user.id)
    found = db.scalar(select(Item).where(Item.user_id == user.id, Item.lcsc_code == code))
    if found is not None:
        return present_item(db, found, catalog)
    try:
        info = fetch_lcsc(code, catalog, user_id=user.id)
    except LcscError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item = Item(
        user_id=user.id,
        lcsc_code=clean_code(info.get("lcsc_code")) or code,
        mpn=info.get("mpn") or "",
        name=info.get("name") or "",
        brand=info.get("brand") or "",
        footprint=info.get("footprint") or "",
        category=info.get("category") or "",
        value=info.get("value") or "",
        params=info.get("params") or "",
        specs=dump_specs(catalog.clean(info.get("category") or "", info.get("specs") or {}, strict=False)),
        datasheet_url=info.get("datasheet_url") or "",
        unit_price=info.get("unit_price"),
        quantity=0,
    )
    db.add(item)
    db.flush()
    assign_image(item, info.get("image_url") or "")
    db.commit()
    db.refresh(item)
    return present_item(db, item, catalog)


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ItemOut:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    return present_item(db, item, load_catalog(db, user.id))


@router.post("", response_model=ItemOut)
def create_item(
    body: ItemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    catalog = load_catalog(db, user.id)
    item = Item(user_id=user.id, quantity=0)
    apply_fields(db, user, item, body, catalog)
    db.add(item)
    db.flush()
    try:
        set_total_quantity(db, user.id, item, body.quantity)
    except StockError as exc:
        raise_stock(exc)
    assign_image(item, body.image_url)
    db.commit()
    db.refresh(item)
    return present_item(db, item, catalog)


@router.put("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int,
    body: ItemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    catalog = load_catalog(db, user.id)
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    if (item.lcsc_sync_status or "") in ("queued", "running"):
        raise HTTPException(status_code=409, detail=BUSY_DETAIL)
    apply_fields(db, user, item, body, catalog)
    try:
        set_total_quantity(db, user.id, item, body.quantity)
    except StockError as exc:
        raise_stock(exc)
    assign_image(item, body.image_url)
    db.commit()
    db.refresh(item)
    return present_item(db, item, catalog)


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    db.execute(update(ProjectLine).where(ProjectLine.matched_item_id == item.id).values(matched_item_id=None))
    delete_item_image(item)
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/{item_id}/unbox", response_model=ItemOut)
def unbox_item_route(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    unbox_item(db, item)
    db.commit()
    db.refresh(item)
    return present_item(db, item, load_catalog(db, user.id))


@router.post("/{item_id}/checkout", response_model=ItemOut)
def checkout_item(
    item_id: int,
    body: ItemCheckoutIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    location = db.get(ItemLocation, body.location_id)
    if location is None or location.item_id != item.id or location.user_id != user.id:
        raise HTTPException(status_code=404, detail="存放位置不存在")
    try:
        checkout_location(db, user.id, item, location, body.quantity)
    except StockError as exc:
        raise_stock(exc)
    db.commit()
    db.refresh(item)
    return present_item(db, item, load_catalog(db, user.id))
