from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Box, Item, ItemLocation, StockEvent, utcnow
from app.schemas import LocationOut


class StockError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def line_value(quantity: int, unit_price: float | None) -> float | None:
    if unit_price is None:
        return None
    return round((quantity or 0) * float(unit_price), 4)


def sync_quantity(db: Session, item: Item) -> None:
    total = db.scalar(
        select(func.coalesce(func.sum(ItemLocation.quantity), 0)).where(ItemLocation.item_id == item.id)
    )
    item.quantity = int(total or 0)
    item.updated_at = utcnow()


def record_event(
    db: Session,
    user_id: int,
    item: Item,
    event_type: str,
    delta: int,
    *,
    project_id: int | None = None,
    note: str = "",
) -> None:
    if not delta:
        return
    db.add(
        StockEvent(
            user_id=user_id,
            item_id=item.id,
            event_type=event_type,
            quantity_delta=delta,
            project_id=project_id,
            note=note,
            created_at=utcnow(),
        )
    )


def locations_of(db: Session, item: Item) -> list[ItemLocation]:
    return list(
        db.scalars(select(ItemLocation).where(ItemLocation.item_id == item.id).order_by(ItemLocation.id)).all()
    )


def location_views(db: Session, item_ids: list[int]) -> dict[int, list[LocationOut]]:
    grouped: dict[int, list[LocationOut]] = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return grouped
    rows = list(
        db.scalars(
            select(ItemLocation).where(ItemLocation.item_id.in_(item_ids)).order_by(ItemLocation.id)
        ).all()
    )
    names = _box_names(db, {row.box_id for row in rows if row.box_id})
    for row in rows:
        grouped.setdefault(row.item_id, []).append(_location_out(row, names.get(row.box_id)))
    return grouped


def place_snapshots(db: Session, item_ids: list[int]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {item_id: [] for item_id in item_ids}
    if not item_ids:
        return grouped
    rows = list(
        db.scalars(
            select(ItemLocation).where(ItemLocation.item_id.in_(item_ids)).order_by(ItemLocation.id)
        ).all()
    )
    names = _box_names(db, {row.box_id for row in rows if row.box_id})
    for row in rows:
        grouped.setdefault(row.item_id, []).append(
            {
                "location_type": row.location_type,
                "box_name": names.get(row.box_id, "") if row.box_id else "",
                "row": row.row,
                "col": row.col,
                "reel_label": row.reel_label or "",
                "slot_index": row.slot_index,
                "quantity": row.quantity or 0,
            }
        )
    return grouped


def set_total_quantity(db: Session, user_id: int, item: Item, new_qty: int) -> None:
    if new_qty < 0:
        raise StockError("库存不能为负数")
    locs = locations_of(db, item)
    placed = sum((loc.quantity or 0) for loc in locs if loc.location_type != "unboxed")
    if new_qty < placed:
        raise StockError("库存不能小于已放在物料盒和料卷中的数量")
    target = new_qty - placed
    current = next(((loc.quantity or 0) for loc in locs if loc.location_type == "unboxed"), 0)
    delta = target - current
    if delta == 0:
        return
    unboxed = next((loc for loc in locs if loc.location_type == "unboxed"), None)
    if target == 0:
        if unboxed is not None:
            db.delete(unboxed)
    else:
        if unboxed is None:
            unboxed = _new_location(item, "unboxed", quantity=target)
            db.add(unboxed)
        else:
            unboxed.quantity = target
            unboxed.updated_at = utcnow()
    db.flush()
    sync_quantity(db, item)
    record_event(db, user_id, item, "stock_in" if delta > 0 else "adjust", delta)


def change_quantity(
    db: Session,
    user_id: int,
    item: Item,
    delta: int,
    *,
    positive: str = "stock_in",
    negative: str = "adjust",
    project_id: int | None = None,
    note: str = "",
) -> None:
    if delta == 0:
        return
    if delta > 0:
        loc = _ensure_unboxed(db, item)
        loc.quantity = (loc.quantity or 0) + delta
        loc.updated_at = utcnow()
        db.flush()
    else:
        _deduct(db, item, -delta)
    sync_quantity(db, item)
    record_event(
        db,
        user_id,
        item,
        positive if delta > 0 else negative,
        delta,
        project_id=project_id,
        note=note,
    )


def checkout_location(
    db: Session,
    user_id: int,
    item: Item,
    location: ItemLocation,
    amount: int,
    *,
    project_id: int | None = None,
) -> None:
    if amount <= 0:
        raise StockError("出库数量需要大于 0")
    if amount > (location.quantity or 0):
        raise StockError("出库数量超过该位置的库存")
    location.quantity = (location.quantity or 0) - amount
    location.updated_at = utcnow()
    db.flush()
    sync_quantity(db, item)
    record_event(db, user_id, item, "checkout", -amount, project_id=project_id, note="单格出库")


def unbox_item(db: Session, item: Item) -> None:
    locs = locations_of(db, item)
    moved = 0
    unboxed = None
    for loc in locs:
        if loc.location_type == "unboxed":
            unboxed = loc
            continue
        moved += loc.quantity or 0
        db.delete(loc)
    db.flush()
    if moved:
        if unboxed is None:
            unboxed = _new_location(item, "unboxed", quantity=moved)
            db.add(unboxed)
        else:
            unboxed.quantity = (unboxed.quantity or 0) + moved
            unboxed.updated_at = utcnow()
        db.flush()
    sync_quantity(db, item)


def release_box(db: Session, box: Box) -> None:
    locs = list(db.scalars(select(ItemLocation).where(ItemLocation.box_id == box.id)).all())
    grouped: dict[int, list[ItemLocation]] = {}
    for loc in locs:
        grouped.setdefault(loc.item_id, []).append(loc)
    for item_id, group in grouped.items():
        item = db.get(Item, item_id)
        if item is None:
            continue
        moved = 0
        for loc in group:
            moved += loc.quantity or 0
            db.delete(loc)
        db.flush()
        if moved:
            unboxed = _ensure_unboxed(db, item)
            unboxed.quantity = (unboxed.quantity or 0) + moved
            unboxed.updated_at = utcnow()
        sync_quantity(db, item)


def add_location(
    db: Session,
    user_id: int,
    item: Item,
    *,
    location_type: str,
    box_id: int | None,
    row: int | None,
    col: int | None,
    reel_label: str,
    slot_index: int | None,
    quantity: int,
) -> ItemLocation:
    if quantity < 0:
        raise StockError("数量不能为负数")
    loc = _resolve_target(
        db,
        user_id,
        item,
        location_type=location_type,
        box_id=box_id,
        row=row,
        col=col,
        reel_label=reel_label,
        slot_index=slot_index,
    )
    if quantity:
        loc.quantity = (loc.quantity or 0) + quantity
        loc.updated_at = utcnow()
        db.flush()
        sync_quantity(db, item)
        record_event(db, user_id, item, "stock_in", quantity, note="新增存放位置")
    return loc


def update_location_quantity(db: Session, user_id: int, loc: ItemLocation, quantity: int) -> Item:
    if quantity < 0:
        raise StockError("数量不能为负数")
    item = _own_item(db, user_id, loc.item_id)
    delta = quantity - (loc.quantity or 0)
    loc.quantity = quantity
    loc.updated_at = utcnow()
    db.flush()
    sync_quantity(db, item)
    if delta:
        record_event(db, user_id, item, "stock_in" if delta > 0 else "adjust", delta, note="调整存放数量")
    return item


def delete_location(db: Session, user_id: int, loc: ItemLocation) -> Item:
    if (loc.quantity or 0) != 0:
        raise StockError("请先把该位置的数量流转或出库，再删除")
    item = _own_item(db, user_id, loc.item_id)
    db.delete(loc)
    db.flush()
    sync_quantity(db, item)
    return item


def transfer(
    db: Session,
    user_id: int,
    *,
    from_location_id: int,
    to_type: str,
    to_box_id: int | None,
    to_row: int | None,
    to_col: int | None,
    to_slot_index: int | None,
    quantity: int,
) -> Item:
    if quantity <= 0:
        raise StockError("流转数量需要大于 0")
    source = db.get(ItemLocation, from_location_id)
    if source is None or source.user_id != user_id:
        raise StockError("来源位置不存在", 404)
    if quantity > (source.quantity or 0):
        raise StockError("流转数量超过该位置的库存")
    item = _own_item(db, user_id, source.item_id)
    target = _resolve_target(
        db,
        user_id,
        item,
        location_type=to_type,
        box_id=to_box_id,
        row=to_row,
        col=to_col,
        slot_index=to_slot_index,
    )
    if target.id == source.id:
        raise StockError("来源和目标是同一个位置")
    source.quantity = (source.quantity or 0) - quantity
    target.quantity = (target.quantity or 0) + quantity
    now = utcnow()
    source.updated_at = now
    target.updated_at = now
    db.flush()
    if (source.quantity or 0) == 0:
        db.delete(source)
        db.flush()
    sync_quantity(db, item)
    return item


def _deduct(db: Session, item: Item, amount: int) -> None:
    remaining = amount
    locs = locations_of(db, item)
    order = {"unboxed": 0, "box_cell": 1, "tape_reel": 2}
    for loc in sorted(locs, key=lambda row: (order.get(row.location_type, 9), row.id)):
        if remaining <= 0:
            break
        available = loc.quantity or 0
        if available <= 0:
            continue
        take = min(available, remaining)
        loc.quantity = available - take
        loc.updated_at = utcnow()
        remaining -= take
    if remaining > 0:
        loc = _ensure_unboxed(db, item)
        loc.quantity = (loc.quantity or 0) - remaining
        loc.updated_at = utcnow()
    db.flush()
    unboxed = db.scalar(
        select(ItemLocation).where(ItemLocation.item_id == item.id, ItemLocation.location_type == "unboxed")
    )
    if unboxed is not None and (unboxed.quantity or 0) == 0:
        db.delete(unboxed)
        db.flush()


def _ensure_unboxed(db: Session, item: Item) -> ItemLocation:
    found = db.scalar(
        select(ItemLocation).where(ItemLocation.item_id == item.id, ItemLocation.location_type == "unboxed")
    )
    if found is not None:
        return found
    loc = _new_location(item, "unboxed", quantity=0)
    db.add(loc)
    db.flush()
    return loc


def _new_location(
    item: Item,
    location_type: str,
    *,
    quantity: int = 0,
    box: Box | None = None,
    row=None,
    col=None,
    reel_label: str = "",
    slot_index: int | None = None,
) -> ItemLocation:
    return ItemLocation(
        item_id=item.id,
        user_id=item.user_id,
        location_type=location_type,
        box_id=box.id if box is not None else None,
        row=row,
        col=col,
        reel_label=reel_label,
        slot_index=slot_index,
        quantity=quantity,
        created_at=utcnow(),
        updated_at=utcnow(),
    )


def _own_item(db: Session, user_id: int, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.user_id != user_id:
        raise StockError("物料不存在", 404)
    return item


def _own_box(db: Session, user_id: int, box_id: int | None) -> Box:
    if box_id is None:
        raise StockError("请选择物料盒")
    box = db.scalar(select(Box).where(Box.id == box_id, Box.user_id == user_id))
    if box is None:
        raise StockError("物料盒不存在")
    return box


def _resolve_target(
    db: Session,
    user_id: int,
    item: Item,
    *,
    location_type: str,
    box_id: int | None,
    row: int | None,
    col: int | None,
    reel_label: str = "",
    slot_index: int | None = None,
) -> ItemLocation:
    if location_type == "unboxed":
        return _ensure_unboxed(db, item)
    if location_type == "box_cell":
        box = _own_box(db, user_id, box_id)
        if box.box_type != "grid":
            raise StockError("格子只能放进格子盒")
        if row is None or col is None:
            raise StockError("放入物料盒时需要填写行和列")
        if row < 1 or col < 1 or row > box.rows or col > box.cols:
            raise StockError("格子超出物料盒范围")
        found = db.scalar(
            select(ItemLocation).where(
                ItemLocation.box_id == box.id,
                ItemLocation.row == row,
                ItemLocation.col == col,
                ItemLocation.location_type == "box_cell",
            )
        )
        if found is not None and found.item_id != item.id:
            raise StockError("该格子已有物料")
        if found is not None:
            return found
        loc = _new_location(item, "box_cell", box=box, row=row, col=col)
        db.add(loc)
        db.flush()
        return loc
    if location_type == "tape_reel":
        box = _own_box(db, user_id, box_id)
        if box.box_type != "reel":
            raise StockError("料卷只能放进料卷盒")
        if slot_index is None:
            raise StockError("请选择料卷槽位")
        capacity = box.slot_count or 0
        if slot_index < 1 or slot_index > capacity:
            raise StockError("料卷槽位超出范围")
        found = db.scalar(
            select(ItemLocation).where(
                ItemLocation.box_id == box.id,
                ItemLocation.location_type == "tape_reel",
                ItemLocation.slot_index == slot_index,
            )
        )
        if found is not None and found.item_id != item.id:
            raise StockError("该槽位已有物料")
        if found is not None:
            return found
        label = (reel_label or "").strip() or str(slot_index)
        loc = _new_location(item, "tape_reel", box=box, reel_label=label, slot_index=slot_index)
        db.add(loc)
        db.flush()
        return loc
    raise StockError("未知的存放类型")


def _box_names(db: Session, box_ids: set[int]) -> dict[int, str]:
    if not box_ids:
        return {}
    return {box_id: name for box_id, name in db.execute(select(Box.id, Box.name).where(Box.id.in_(box_ids))).all()}


def _location_out(loc: ItemLocation, box_name: str | None) -> LocationOut:
    return LocationOut(
        id=loc.id,
        item_id=loc.item_id,
        location_type=loc.location_type,
        box_id=loc.box_id,
        box_name=box_name,
        row=loc.row,
        col=loc.col,
        reel_label=loc.reel_label or "",
        slot_index=loc.slot_index,
        quantity=loc.quantity or 0,
    )
