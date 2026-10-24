from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Box, Item, Project, ProjectLine, User, utcnow
from app.routers.items import item_out
from app.schemas import BoxIn, BoxOut, BoxMapOut, CellOut, MapOut, MapStats

router = APIRouter(tags=["boxes"])


def _own_box(db: Session, user: User, box_id: int) -> Box:
    box = db.scalar(select(Box).where(Box.id == box_id, Box.user_id == user.id))
    if box is None:
        raise HTTPException(status_code=404, detail="物料盒不存在")
    return box


def _check_shape(data: BoxIn) -> None:
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写物料盒名称")
    if data.rows < 1 or data.cols < 1 or data.rows > 100 or data.cols > 100:
        raise HTTPException(status_code=400, detail="行数和列数需要在 1 到 100 之间")


@router.get("/api/boxes", response_model=list[BoxOut])
def list_boxes(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Box]:
    return list(db.scalars(select(Box).where(Box.user_id == user.id).order_by(Box.id)).all())


@router.post("/api/boxes", response_model=BoxOut)
def create_box(body: BoxIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Box:
    _check_shape(body)
    name = body.name.strip()
    if db.scalar(select(Box.id).where(Box.user_id == user.id, Box.name == name)):
        raise HTTPException(status_code=400, detail="物料盒名称已存在")
    box = Box(user_id=user.id, name=name, rows=body.rows, cols=body.cols, remark=body.remark.strip())
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
    _check_shape(body)
    name = body.name.strip()
    taken = db.scalar(select(Box.id).where(Box.user_id == user.id, Box.name == name, Box.id != box.id))
    if taken:
        raise HTTPException(status_code=400, detail="物料盒名称已存在")
    outside = db.scalar(
        select(Item.id).where(
            Item.box_id == box.id,
            or_(Item.row > body.rows, Item.col > body.cols),
        )
    )
    if outside:
        raise HTTPException(status_code=400, detail="缩小行列前请先移走超出范围的物料")
    box.name = name
    box.rows = body.rows
    box.cols = body.cols
    box.remark = body.remark.strip()
    db.commit()
    db.refresh(box)
    return box


@router.delete("/api/boxes/{box_id}")
def delete_box(box_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    box = _own_box(db, user, box_id)
    items = db.scalars(select(Item).where(Item.box_id == box.id)).all()
    for item in items:
        item.box_id = None
        item.row = None
        item.col = None
        item.updated_at = utcnow()
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
    rows = db.execute(
        select(Item, Box.name)
        .outerjoin(Box, Item.box_id == Box.id)
        .where(Item.user_id == user.id)
        .order_by(Item.id)
    ).all()
    items = [(item, box_name) for item, box_name in rows]
    categories = sorted({item.category for item, _name in items if item.category})
    selected = category.strip()
    highlights: dict[str, list[str]] = {}
    if project_id is not None:
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

    by_box: dict[int, list[tuple[Item, str | None]]] = {box.id: [] for box in boxes}
    unboxed = []
    for item, box_name in items:
        if item.box_id in by_box:
            by_box[item.box_id].append((item, box_name))
        else:
            unboxed.append(item_out(item, None))

    box_maps: list[BoxMapOut] = []
    for box in boxes:
        placed: dict[tuple[int, int], ItemOut] = {}
        invalid = []
        for item, box_name in by_box[box.id]:
            view = item_out(item, box_name)
            if item.row is None or item.col is None or item.row < 1 or item.col < 1 or item.row > box.rows or item.col > box.cols:
                invalid.append(view)
                continue
            placed[(item.row, item.col)] = view
        cells = []
        for row in range(1, box.rows + 1):
            for col in range(1, box.cols + 1):
                item_view = placed.get((row, col))
                dimmed = bool(item_view and selected and item_view.category != selected)
                cells.append(CellOut(row=row, col=col, item=item_view, dimmed=dimmed))
        box_maps.append(
            BoxMapOut(
                id=box.id,
                name=box.name,
                rows=box.rows,
                cols=box.cols,
                remark=box.remark or "",
                cells=cells,
                invalid_items=invalid,
            )
        )
    return MapOut(
        stats=MapStats(
            item_count=len(items),
            box_count=len(boxes),
            quantity_total=sum(item.quantity or 0 for item, _name in items),
        ),
        categories=categories,
        boxes=box_maps,
        unboxed=unboxed,
        highlights=highlights,
    )
