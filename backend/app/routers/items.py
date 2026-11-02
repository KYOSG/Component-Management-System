from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Item, ItemLocation, ProjectLine, User, utcnow
from app.schemas import ItemCheckoutIn, ItemIn, ItemOut, ItemPage, LcscCreateIn
from app.services.images import assign_image, delete_item_image, display_image_url
from app.services.lcsc import LcscError, fetch_lcsc
from app.services.spec_config import load_catalog
from app.services.specs import SpecCatalog, SpecValidationError, dump_specs, load_specs
from app.services.stock import (
    StockError,
    checkout_location,
    line_value,
    location_views,
    set_total_quantity,
    unbox_item,
)

router = APIRouter(prefix="/api/items", tags=["items"])


def clean_code(value: str | None) -> str | None:
    text = (value or "").strip()
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
        unit_price=price,
        total_value=line_value(item.quantity or 0, price),
        locations=locations,
        datasheet_url=item.datasheet_url or "",
        image_url=display_image_url(item.image_url or ""),
        remark=item.remark or "",
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
    item.unit_price = data.unit_price
    item.datasheet_url = data.datasheet_url.strip()
    item.remark = data.remark.strip()
    item.updated_at = utcnow()


def contains(column, text: str):
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.like(f"%{escaped}%", escape="\\")


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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemPage:
    filters = [Item.user_id == user.id]
    keyword = q.strip()
    if keyword:
        filters.append(
            or_(
                contains(Item.lcsc_code, keyword),
                contains(Item.mpn, keyword),
                contains(Item.name, keyword),
                contains(Item.brand, keyword),
                contains(Item.footprint, keyword),
                contains(Item.category, keyword),
                contains(Item.value, keyword),
            )
        )
    for column, text in (
        (Item.lcsc_code, lcsc_code),
        (Item.mpn, mpn),
        (Item.name, name),
        (Item.footprint, footprint),
        (Item.category, category),
        (Item.remark, remark),
    ):
        if text.strip():
            filters.append(contains(column, text.strip()))
    total = db.scalar(select(func.count()).select_from(Item).where(*filters)) or 0
    catalog = load_catalog(db, user.id)
    rows = list(
        db.scalars(
            select(Item).where(*filters).order_by(Item.id.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    return ItemPage(
        total=total,
        page=page,
        page_size=page_size,
        items=present_items(db, rows, catalog),
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
    found = db.scalar(select(Item).where(Item.user_id == user.id, func.lower(Item.lcsc_code) == code.lower()))
    if found is not None:
        return present_item(db, found, catalog)
    try:
        info = fetch_lcsc(code, catalog)
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
