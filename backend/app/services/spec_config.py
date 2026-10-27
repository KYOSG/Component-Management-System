from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SpecCategory, utcnow
from app.services.specs import CatalogCategory, SpecCatalog, SpecField, default_catalog, field_to_dict


def _load_json(raw: str | None, fallback: list) -> list:
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError:
        return fallback
    return data if isinstance(data, list) else fallback


def _texts(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    output: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in output:
            output.append(text)
    return tuple(output)


def category_from_row(row: SpecCategory) -> CatalogCategory:
    fields: list[SpecField] = []
    for item in _load_json(row.fields, []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if not key or not label:
            continue
        field_type = str(item.get("type") or "text")
        if field_type not in {"text", "number", "select"}:
            field_type = "text"
        fields.append(
            SpecField(
                key=key,
                label=label,
                type=field_type,
                unit=str(item.get("unit") or "").strip(),
                options=_texts(item.get("options")),
                aliases=_texts(item.get("aliases")),
                required=bool(item.get("required")),
            )
        )
    return CatalogCategory(
        name=row.name,
        lcsc_keywords=_texts(_load_json(row.lcsc_keywords, [])),
        fields=tuple(fields),
    )


def load_catalog(db: Session, user_id: int) -> SpecCatalog:
    rows = db.scalars(
        select(SpecCategory)
        .where(SpecCategory.user_id == user_id)
        .order_by(SpecCategory.sort_order, SpecCategory.id)
    ).all()
    return SpecCatalog([category_from_row(row) for row in rows])


def seed_defaults(db: Session, user_id: int) -> None:
    exists = db.scalar(select(SpecCategory.id).where(SpecCategory.user_id == user_id).limit(1))
    if exists:
        return
    now = utcnow()
    for index, category in enumerate(default_catalog().categories):
        db.add(
            SpecCategory(
                user_id=user_id,
                name=category.name,
                lcsc_keywords=json.dumps(list(category.lcsc_keywords), ensure_ascii=False),
                fields=json.dumps([field_to_dict(field) for field in category.fields], ensure_ascii=False),
                sort_order=index,
                created_at=now,
                updated_at=now,
            )
        )


def category_to_dict(row: SpecCategory) -> dict:
    category = category_from_row(row)
    return {
        "id": row.id,
        "name": category.name,
        "lcsc_keywords": list(category.lcsc_keywords),
        "fields": [field_to_dict(field) for field in category.fields],
        "sort_order": row.sort_order,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
