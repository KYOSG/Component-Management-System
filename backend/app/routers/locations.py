from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Item, ItemLocation, User
from app.routers.items import present_item, raise_stock
from app.schemas import ItemOut, LocationIn, LocationOut, LocationUpdate
from app.services.spec_config import load_catalog
from app.services.stock import StockError, add_location, delete_location, location_views, update_location_quantity

router = APIRouter(tags=["locations"])


@router.get("/api/items/{item_id}/locations", response_model=list[LocationOut])
def list_locations(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[LocationOut]:
    item = db.get(Item, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="物料不存在")
    return location_views(db, [item.id]).get(item.id, [])


@router.post("/api/items/{item_id}/locations", response_model=ItemOut)
def create_location(
    item_id: int,
    body: LocationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    item = db.get(Item, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="物料不存在")
    try:
        add_location(
            db,
            user.id,
            item,
            location_type=body.location_type,
            box_id=body.box_id,
            row=body.row,
            col=body.col,
            reel_label=body.reel_label,
            slot_index=body.slot_index,
            quantity=body.quantity,
        )
    except StockError as exc:
        raise_stock(exc)
    db.commit()
    db.refresh(item)
    return present_item(db, item, load_catalog(db, user.id))


@router.put("/api/locations/{location_id}", response_model=ItemOut)
def update_location(
    location_id: int,
    body: LocationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    loc = db.get(ItemLocation, location_id)
    if loc is None or loc.user_id != user.id:
        raise HTTPException(status_code=404, detail="存放位置不存在")
    try:
        item = update_location_quantity(db, user.id, loc, body.quantity)
    except StockError as exc:
        raise_stock(exc)
    db.commit()
    db.refresh(item)
    return present_item(db, item, load_catalog(db, user.id))


@router.delete("/api/locations/{location_id}", response_model=ItemOut)
def remove_location(
    location_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    loc = db.get(ItemLocation, location_id)
    if loc is None or loc.user_id != user.id:
        raise HTTPException(status_code=404, detail="存放位置不存在")
    try:
        item = delete_location(db, user.id, loc)
    except StockError as exc:
        raise_stock(exc)
    db.commit()
    db.refresh(item)
    return present_item(db, item, load_catalog(db, user.id))
