from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Box, Item, Project, ProjectLine, utcnow
from app.services.system_config import read_settings
from app.services.match import ItemSnap, LineSnap, match_lines


def apply_match(db: Session, user_id: int, project: Project) -> None:
    item_rows = db.execute(
        select(Item, Box.name)
        .outerjoin(Box, Item.box_id == Box.id)
        .where(Item.user_id == user_id)
        .order_by(Item.id)
    ).all()
    items = [
        ItemSnap(
            id=item.id,
            lcsc_code=item.lcsc_code or "",
            mpn=item.mpn or "",
            name=item.name or "",
            brand=item.brand or "",
            footprint=item.footprint or "",
            category=item.category or "",
            value=item.value or "",
            params=item.params or "",
            quantity=item.quantity or 0,
            box_name=box_name or "",
            row=item.row,
            col=item.col,
        )
        for item, box_name in item_rows
    ]
    lines = db.scalars(
        select(ProjectLine)
        .where(ProjectLine.project_id == project.id)
        .order_by(ProjectLine.line_no, ProjectLine.id)
    ).all()
    purchase_sets = project.purchase_sets or 1
    if purchase_sets < 1:
        purchase_sets = 1
    for line in lines:
        line.quantity_required = (line.quantity_per_board or 0) * purchase_sets
    snaps = [
        LineSnap(
            id=line.id,
            designators=line.designators or "",
            quantity_per_board=line.quantity_per_board or 0,
            quantity_required=line.quantity_required or 0,
            lcsc_code=line.lcsc_code or "",
            mpn=line.mpn or "",
            brand=line.brand or "",
            footprint=line.footprint or "",
            value=line.value or "",
            params=line.params or "",
            product_name=line.product_name or "",
            category=line.category or "",
        )
        for line in lines
    ]
    matched_at = utcnow()
    ai = read_settings(db)
    for line, result in zip(
        lines,
        match_lines(
            snaps,
            items,
            ai_enabled=ai.ai_enabled,
            api_key=ai.deepseek_api_key,
            base_url=ai.deepseek_base_url,
            model=ai.deepseek_model,
        ),
    ):
        line.match_status = result.status
        line.matched_item_id = result.matched_item_id
        line.suggestions_json = json.dumps(result.suggestions, ensure_ascii=False)
        line.matched_at = matched_at
