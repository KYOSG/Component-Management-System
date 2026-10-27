from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Item, SpecCategory, User, utcnow
from app.schemas import SpecCategoryIn, SpecCategoryOut
from app.services.spec_config import category_to_dict

router = APIRouter(prefix="/api/spec-categories", tags=["spec-categories"])


def _own(db: Session, user: User, category_id: int) -> SpecCategory:
    row = db.scalar(select(SpecCategory).where(SpecCategory.id == category_id, SpecCategory.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="类目不存在")
    return row


def _name_taken(db: Session, user: User, name: str, exclude_id: int | None = None) -> bool:
    filters = [SpecCategory.user_id == user.id, SpecCategory.name == name]
    if exclude_id is not None:
        filters.append(SpecCategory.id != exclude_id)
    return db.scalar(select(SpecCategory.id).where(*filters)) is not None


def _apply(row: SpecCategory, body: SpecCategoryIn, sort_order: int) -> None:
    row.name = body.name
    row.lcsc_keywords = json.dumps(body.lcsc_keywords, ensure_ascii=False)
    row.fields = json.dumps([field.model_dump() for field in body.fields], ensure_ascii=False)
    row.sort_order = sort_order
    row.updated_at = utcnow()


def _out(row: SpecCategory) -> SpecCategoryOut:
    return SpecCategoryOut(**category_to_dict(row))


@router.get("", response_model=list[SpecCategoryOut])
def list_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SpecCategoryOut]:
    rows = db.scalars(
        select(SpecCategory)
        .where(SpecCategory.user_id == user.id)
        .order_by(SpecCategory.sort_order, SpecCategory.id)
    ).all()
    return [_out(row) for row in rows]


@router.post("", response_model=SpecCategoryOut)
def create_category(
    body: SpecCategoryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SpecCategoryOut:
    if _name_taken(db, user, body.name):
        raise HTTPException(status_code=400, detail="类目名称已存在")
    if body.sort_order is None:
        current = db.scalar(select(func.max(SpecCategory.sort_order)).where(SpecCategory.user_id == user.id))
        sort_order = 0 if current is None else current + 1
    else:
        sort_order = body.sort_order
    row = SpecCategory(user_id=user.id, name=body.name, created_at=utcnow())
    _apply(row, body, sort_order)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.put("/{category_id}", response_model=SpecCategoryOut)
def update_category(
    category_id: int,
    body: SpecCategoryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SpecCategoryOut:
    row = _own(db, user, category_id)
    if body.name != row.name:
        if _name_taken(db, user, body.name, exclude_id=row.id):
            raise HTTPException(status_code=400, detail="类目名称已存在")
        db.execute(
            update(Item)
            .where(Item.user_id == user.id, Item.category == row.name)
            .values(category=body.name, updated_at=utcnow())
        )
    sort_order = row.sort_order if body.sort_order is None else body.sort_order
    _apply(row, body, sort_order)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _own(db, user, category_id)
    db.delete(row)
    db.commit()
    return {"ok": True}
