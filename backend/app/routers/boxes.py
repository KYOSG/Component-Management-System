from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Box, Item, ItemLocation, Project, ProjectLine, User
from app.routers.items import item_out
from app.schemas import BoxIn, BoxMapOut, BoxOut, CellOut, ItemOut, MapOut, MapStats, PlacedItemOut, ReelSlotOut
from app.services.spec_config import load_catalog
from app.services.stock import StockError, line_value, location_views, release_box

router = APIRouter(tags=["boxes"])


def _own_box(db: Session, user: User, box_id: int) -> Box:
    box = db.scalar(select(Box).where(Box.id == box_id, Box.user_id == user.id))
    if box is None:
        raise HTTPException(status_code=404, detail="物料盒不存在")
    return box


def _check_box(data: BoxIn) -> None:
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写物料盒名称")
    if data.box_type == "reel":
        if data.slot_count < 1 or data.slot_count > 100:
            raise HTTPException(status_code=400, detail="最大卷数需要在 1 到 100 之间")
        return
    if data.rows < 1 or data.cols < 1 or data.rows > 100 or data.cols > 100:
        raise HTTPException(status_code=400, detail="行数和列数需要在 1 到 100 之间")


def _shape(data: BoxIn) -> tuple[int, int, int]:
    if data.box_type == "reel":
        return 0, 0, data.slot_count
    return data.rows, data.cols, 0


@router.get("/api/boxes", response_model=list[BoxOut])
def list_boxes(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Box]:
    return list(db.scalars(select(Box).where(Box.user_id == user.id).order_by(Box.id)).all())


@router.post("/api/boxes", response_model=BoxOut)
def create_box(body: BoxIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Box:
    _check_box(body)
    name = body.name.strip()
    if db.scalar(select(Box.id).where(Box.user_id == user.id, Box.name == name)):
        raise HTTPException(status_code=400, detail="物料盒名称已存在")
    rows, cols, slot_count = _shape(body)
    box = Box(
        user_id=user.id,
        name=name,
        box_type=body.box_type,
        rows=rows,
        cols=cols,
        slot_count=slot_count,
        remark=body.remark.strip(),
    )
    db.add(box)
    db.commit()
    db.refresh(box)
    return box


@router.put("/api/boxes/{box_id}", response_model=BoxOut)
def update_box(
    box_id: int,
    body: BoxIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Box:
    box = _own_box(db, user, box_id)
    _check_box(body)
    name = body.name.strip()
    taken = db.scalar(select(Box.id).where(Box.user_id == user.id, Box.name == name, Box.id != box.id))
    if taken:
        raise HTTPException(status_code=400, detail="物料盒名称已存在")
    if body.box_type != box.box_type:
        occupied = db.scalar(select(ItemLocation.id).where(ItemLocation.box_id == box.id))
        if occupied:
            raise HTTPException(status_code=400, detail="盒内还有物料，不能更改类型")
    if body.box_type == "grid":
        outside = db.scalar(
            select(ItemLocation.id).where(
                ItemLocation.box_id == box.id,
                ItemLocation.location_type == "box_cell",
                or_(ItemLocation.row > body.rows, ItemLocation.col > body.cols),
            )
        )
        if outside:
            raise HTTPException(status_code=400, detail="缩小行列前请先移走超出范围的物料")
    if body.box_type == "reel":
        outside = db.scalar(
            select(ItemLocation.id).where(
                ItemLocation.box_id == box.id,
                ItemLocation.location_type == "tape_reel",
                or_(ItemLocation.slot_index.is_(None), ItemLocation.slot_index > body.slot_count),
            )
        )
        if outside:
            raise HTTPException(status_code=400, detail="缩小卷数前请先移走超出范围的料卷")
    rows, cols, slot_count = _shape(body)
    box.name = name
    box.box_type = body.box_type
    box.rows = rows
    box.cols = cols
    box.slot_count = slot_count
    box.remark = body.remark.strip()
    db.commit()
    db.refresh(box)
    return box


@router.delete("/api/boxes/{box_id}")
def delete_box(box_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    box = _own_box(db, user, box_id)
    try:
        release_box(db, box)
    except StockError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.delete(box)
    db.commit()
    return {"ok": True}


def _split_designators(text: str) -> list[str]:
    return [part for part in re.split(r"[,，\s]+", (text or "").strip()) if part]


@router.get("/api/map", response_model=MapOut)
def inventory_map(
    category: str = "",
    project_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MapOut:
    boxes = list(db.scalars(select(Box).where(Box.user_id == user.id).order_by(Box.id)).all())
    items = list(db.scalars(select(Item).where(Item.user_id == user.id).order_by(Item.id)).all())
    catalog = load_catalog(db, user.id)
    views = location_views(db, [item.id for item in items])
    shown = {item.id: item_out(item, catalog, views.get(item.id, [])) for item in items}
    categories = sorted({item.category for item in items if item.category})
    selected = category.strip()
    highlights = _highlights(db, user, project_id)

    locations = list(
        db.scalars(select(ItemLocation).where(ItemLocation.user_id == user.id).order_by(ItemLocation.id)).all()
    )
    by_box: dict[int, list[ItemLocation]] = {box.id: [] for box in boxes}
    unboxed: list[PlacedItemOut] = []
    for loc in locations:
        if loc.location_type == "unboxed":
            item = shown.get(loc.item_id)
            if item is None or (loc.quantity or 0) == 0:
                continue
            unboxed.append(
                PlacedItemOut(
                    **item.model_dump(),
                    location_id=loc.id,
                    location_quantity=loc.quantity or 0,
                    cell_value=line_value(loc.quantity or 0, item.unit_price),
                )
            )
            continue
        if loc.box_id in by_box:
            by_box[loc.box_id].append(loc)

    box_maps = [_box_map(box, by_box[box.id], shown, selected) for box in boxes]
    total_value = 0.0
    for item in items:
        if item.unit_price is not None:
            total_value += (item.quantity or 0) * float(item.unit_price)
    return MapOut(
        stats=MapStats(
            item_count=len(items),
            box_count=len(boxes),
            quantity_total=sum(item.quantity or 0 for item in items),
            total_value=round(total_value, 4),
        ),
        categories=categories,
        boxes=box_maps,
        unboxed=unboxed,
        highlights=highlights,
    )


def _box_map(box: Box, locs: list[ItemLocation], shown: dict[int, ItemOut], selected: str) -> BoxMapOut:
    if box.box_type == "reel":
        capacity = box.slot_count or 0
        occupied: dict[int, ItemLocation] = {}
        invalid = []
        for loc in locs:
            item = shown.get(loc.item_id)
            if item is None:
                continue
            index = loc.slot_index
            if loc.location_type != "tape_reel" or index is None or index < 1 or index > capacity or index in occupied:
                invalid.append(item)
                continue
            occupied[index] = loc
        slots = []
        for index in range(1, capacity + 1):
            loc = occupied.get(index)
            item = shown.get(loc.item_id) if loc is not None else None
            dimmed = bool(item and selected and item.category != selected)
            slots.append(
                ReelSlotOut(
                    slot_index=index,
                    location_id=loc.id if loc is not None else None,
                    reel_label=(loc.reel_label if loc is not None else "") or str(index),
                    quantity=(loc.quantity or 0) if loc is not None else 0,
                    cell_value=line_value(loc.quantity or 0, item.unit_price) if loc is not None and item is not None else None,
                    dimmed=dimmed,
                    item=item,
                )
            )
        return BoxMapOut(
            id=box.id,
            name=box.name,
            box_type=box.box_type,
            rows=box.rows,
            cols=box.cols,
            slot_count=capacity,
            remark=box.remark or "",
            cells=[],
            reel_slots=slots,
            invalid_items=invalid,
        )

    placed: dict[tuple[int, int], ItemLocation] = {}
    invalid = []
    for loc in locs:
        item = shown.get(loc.item_id)
        if item is None:
            continue
        if loc.location_type != "box_cell" or loc.row is None or loc.col is None:
            invalid.append(item)
            continue
        if loc.row < 1 or loc.col < 1 or loc.row > box.rows or loc.col > box.cols:
            invalid.append(item)
            continue
        placed[(loc.row, loc.col)] = loc
    cells = []
    for row in range(1, box.rows + 1):
        for col in range(1, box.cols + 1):
            loc = placed.get((row, col))
            item = shown.get(loc.item_id) if loc is not None else None
            dimmed = bool(item and selected and item.category != selected)
            cells.append(
                CellOut(
                    row=row,
                    col=col,
                    item=item,
                    location_id=loc.id if loc is not None else None,
                    location_quantity=(loc.quantity or 0) if loc is not None else 0,
                    cell_value=line_value(loc.quantity or 0, item.unit_price) if loc is not None and item is not None else None,
                    dimmed=dimmed,
                )
            )
    return BoxMapOut(
        id=box.id,
        name=box.name,
        box_type=box.box_type or "grid",
        rows=box.rows,
        cols=box.cols,
        slot_count=0,
        remark=box.remark or "",
        cells=cells,
        reel_slots=[],
        invalid_items=invalid,
    )


def _highlights(db: Session, user: User, project_id: int | None) -> dict[str, list[str]]:
    highlights: dict[str, list[str]] = {}
    if project_id is None:
        return highlights
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    lines = db.scalars(select(ProjectLine).where(ProjectLine.project_id == project.id)).all()
    for line in lines:
        if line.match_status not in {"matched", "insufficient", "suggested"} or not line.matched_item_id:
            continue
        marks = _split_designators(line.designators)
        if not marks:
            continue
        key = str(line.matched_item_id)
        highlights.setdefault(key, [])
        for mark in marks:
            if mark not in highlights[key]:
                highlights[key].append(mark)
    return highlights
