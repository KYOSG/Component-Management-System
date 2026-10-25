from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Box, Item, Project, ProjectLine, utcnow
from app.services.deepseek import AiRun
from app.services.system_config import read_settings
from app.services.match import ItemSnap, LineSnap, ai_jobs, exact_lcsc_result, local_match_lines, run_ai, settle_ai


def _write(line: ProjectLine, result, matched_at) -> None:
    line.match_status = result.status
    line.matched_item_id = result.matched_item_id
    line.suggestions_json = json.dumps(result.suggestions, ensure_ascii=False)
    line.matched_at = matched_at


def _context(db: Session, user_id: int, project: Project):
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
    ai = read_settings(db)
    # 先提交，避免后面的网络请求占着 SQLite 写锁。
    db.commit()
    return items, lines, snaps, ai


def apply_match(db: Session, user_id: int, project: Project) -> None:
    items, lines, snaps, ai = _context(db, user_id, project)
    matched_at = utcnow()
    for line, result in zip(lines, local_match_lines(snaps, items, ai_enabled=ai.ai_enabled)):
        _write(line, result, matched_at)
    db.commit()


def recommend_pending(project_id: int, user_id: int, run: AiRun, on_line: Callable[[ProjectLine], None]) -> None:
    db = SessionLocal()
    try:
        project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user_id))
        if project is None:
            return
        items, lines, snaps, ai = _context(db, user_id, project)
        if not ai.ai_enabled or run.cancel.is_set():
            return
        pending_ids: list[int] = []
        for line in lines:
            try:
                saved = json.loads(line.suggestions_json or "{}")
            except json.JSONDecodeError:
                saved = {}
            if isinstance(saved, dict) and saved.get("source") == "pending":
                pending_ids.append(line.id)
        if not pending_ids:
            return
        snap_by_id = {snap.id: snap for snap in snaps}
        orm_by_id = {line.id: line for line in lines}
        still_pending: list[int] = []
        matched_at = utcnow()
        for line_id in pending_ids:
            snap = snap_by_id.get(line_id)
            orm = orm_by_id.get(line_id)
            if snap is None or orm is None:
                continue
            exact = exact_lcsc_result(snap, items)
            if exact is None:
                still_pending.append(line_id)
                continue
            _write(orm, exact, matched_at)
            db.commit()
            on_line(orm)
        jobs = ai_jobs([snap_by_id[line_id] for line_id in still_pending if line_id in snap_by_id], items)
        if not jobs:
            return
        ranked_by_id = {snap.id: ranked for snap, ranked, _payload in jobs}
        payloads = [payload for _snap, _ranked, payload in jobs]
        db.commit()

        def on_batch(part: dict) -> None:
            if run.cancel.is_set():
                return
            matched_at = utcnow()
            for line_id, picks in part.items():
                snap = snap_by_id.get(int(line_id))
                ranked = ranked_by_id.get(int(line_id))
                orm = orm_by_id.get(int(line_id))
                if snap is None or ranked is None or orm is None:
                    continue
                _write(orm, settle_ai(snap, ranked, picks), matched_at)
                db.commit()
                on_line(orm)

        run_ai(
            payloads,
            api_key=ai.deepseek_api_key,
            base_url=ai.deepseek_base_url,
            model=ai.deepseek_model,
            run=run,
            on_batch=on_batch,
        )
    finally:
        db.close()

