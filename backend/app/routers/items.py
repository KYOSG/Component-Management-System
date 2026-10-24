from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Box, Item, ProjectLine, User, utcnow
from app.schemas import ItemIn, ItemOut, ItemPage
from app.services.specs import clean_specs, dump_specs, load_specs

router = APIRouter(prefix="/api/items", tags=["items"])


def clean_code(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def item_out(item: Item, box_name: str | None = None) -> ItemOut:
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
        specs=load_specs(item.specs),
        quantity=item.quantity or 0,
        box_id=item.box_id,
        box_name=box_name,
        row=item.row,
        col=item.col,
        datasheet_url=item.datasheet_url or "",
        image_url=item.image_url or "",
        remark=item.remark or "",
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def apply_fields(db: Session, user: User, item: Item, data: ItemIn) -> None:
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
    box_id = data.box_id
    row = data.row
    col = data.col
    if box_id is None:
        row = None
        col = None
    else:
        box = db.scalar(select(Box).where(Box.id == box_id, Box.user_id == user.id))
        if box is None:
            raise HTTPException(status_code=400, detail="物料盒不存在")
        if row is None or col is None:
            raise HTTPException(status_code=400, detail="放入物料盒时需要填写行和列")
        if row < 1 or col < 1 or row > box.rows or col > box.cols:
            raise HTTPException(status_code=400, detail="格子超出物料盒范围")
        occupied = db.scalar(
            select(Item.id).where(
                Item.box_id == box_id,
                Item.row == row,
                Item.col == col,
                Item.id != (item.id or 0),
            )
        )
        if occupied:
            raise HTTPException(status_code=400, detail="该格子已有物料")
    item.lcsc_code = code
    item.mpn = data.mpn.strip()
    item.name = data.name.strip()
    item.brand = data.brand.strip()
    item.footprint = data.footprint.strip()
    item.category = data.category.strip()
    item.value = data.value.strip()
    item.params = data.params.strip()
    item.specs = dump_specs(clean_specs(item.category, data.specs))
    item.quantity = data.quantity
    item.box_id = box_id
    item.row = row
    item.col = col
    item.datasheet_url = data.datasheet_url.strip()
    item.image_url = data.image_url.strip()
    item.remark = data.remark.strip()
    item.updated_at = utcnow()


def contains(column, text: str):
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.like(f"%{escaped}%", escape="\\")


@router.get("", response_model=ItemPage)
def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
    rows = db.execute(
        select(Item, Box.name)
        .outerjoin(Box, Item.box_id == Box.id)
        .where(*filters)
        .order_by(Item.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ItemPage(
        total=total,
        page=page,
        page_size=page_size,
        items=[item_out(item, box_name) for item, box_name in rows],
    )


@router.post("", response_model=ItemOut)
def create_item(
    body: ItemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    item = Item(user_id=user.id)
    apply_fields(db, user, item, body)
    db.add(item)
    db.commit()
    db.refresh(item)
    box_name = db.scalar(select(Box.name).where(Box.id == item.box_id)) if item.box_id else None
    return item_out(item, box_name)


@router.put("/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int,
    body: ItemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    apply_fields(db, user, item, body)
    db.commit()
    db.refresh(item)
    box_name = db.scalar(select(Box.name).where(Box.id == item.box_id)) if item.box_id else None
    return item_out(item, box_name)


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    db.execute(
        update(ProjectLine)
        .where(ProjectLine.matched_item_id == item.id)
        .values(matched_item_id=None)
    )
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/{item_id}/unbox", response_model=ItemOut)
def unbox_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    item = db.scalar(select(Item).where(Item.id == item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="物料不存在")
    item.box_id = None
    item.row = None
    item.col = None
    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)
    return item_out(item, None)
