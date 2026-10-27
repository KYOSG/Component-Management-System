from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Box, Item, Project, ProjectLine, User, utcnow
from app.schemas import AdoptOut, BulkAddOut, CheckoutOut, LineOut, ProjectBrief, ProjectOut, ProjectUpdate, ReplaceIn, StockDeltaIn
from app.services.bom import BomError, ParsedLine, parse_upload
from app.services.lcsc import LcscError, fetch_lcsc
from app.services.deepseek import AiRun
from app.services.match import footprint_main, norm_value
from app.services.matching import apply_match, recommend_pending
from app.services.system_config import read_settings
from app.services.spec_config import load_catalog
from app.services.specs import SpecCatalog, default_catalog, dump_specs, parse_params

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])


def _location(record: dict) -> str:
    if record.get("box_name") and record.get("row") and record.get("col"):
        place = f"{record['box_name']} {record['row']}-{record['col']}"
    else:
        place = "未入盒"
    return f"{place}（库存 {record.get('quantity', 0)}）"


def line_out(line: ProjectLine, *, include_match: bool = True) -> LineOut:
    suggestions: dict = {}
    if include_match:
        try:
            suggestions = json.loads(line.suggestions_json or "{}")
        except json.JSONDecodeError:
            suggestions = {}
        if not isinstance(suggestions, dict):
            suggestions = {}
    records = suggestions.get("exact_hits") or suggestions.get("candidates") or []
    risks = suggestions.get("risks") or []
    if not isinstance(risks, list):
        risks = []
    stock = records[0].get("quantity") if records and isinstance(records[0], dict) else None
    return LineOut(
        id=line.id,
        line_no=line.line_no,
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
        match_status=(line.match_status or "") if include_match else "",
        matched_item_id=line.matched_item_id if include_match else None,
        reason="" if suggestions.get("reason") == "立创编号一致" else (suggestions.get("reason") or ""),
        risks=[risk for risk in risks if isinstance(risk, str)],
        locations=[_location(record) for record in records if isinstance(record, dict)],
        stock=stock,
        matched_at=line.matched_at if include_match else None,
    )


def project_out(db: Session, project: Project) -> ProjectOut:
    lines = db.scalars(
        select(ProjectLine).where(ProjectLine.project_id == project.id).order_by(ProjectLine.line_no, ProjectLine.id)
    ).all()
    ai_enabled = read_settings(db).ai_enabled
    return ProjectOut(
        id=project.id,
        name=project.name,
        source_filename=project.source_filename,
        format=project.format,
        purchase_sets=project.purchase_sets,
        order_no=project.order_no or "",
        imported_at=project.imported_at,
        line_count=len(lines),
        ai_enabled=ai_enabled,
        lines=[line_out(line) for line in lines],
    )


def _enrich_lines(lines: list[ParsedLine], catalog: SpecCatalog | None = None) -> None:
    catalog = default_catalog() if catalog is None else catalog
    targets = [line for line in lines if line.needs_lcsc_enrich and line.lcsc_code]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = {pool.submit(fetch_lcsc, line.lcsc_code, catalog): line for line in targets}
        for future in as_completed(futures):
            line = futures[future]
            try:
                info = future.result()
            except Exception:
                logger.warning("立创编号 %s 查询失败，保留 BOM 原值", line.lcsc_code)
                continue
            line.mpn = info.get("mpn") or line.mpn
            line.brand = info.get("brand") or line.brand
            line.footprint = info.get("footprint") or line.footprint
            line.value = info.get("value") or line.value
            line.params = info.get("params") or line.params
            line.product_name = info.get("name") or line.product_name
            line.category = info.get("category") or line.category


def _find_lib_item(db: Session, user_id: int, line: ProjectLine) -> Item | None:
    code = (line.lcsc_code or "").strip()
    if code:
        return db.scalar(select(Item).where(Item.user_id == user_id, Item.lcsc_code == code))
    category = (line.category or "").strip()
    footprint = footprint_main(line.footprint or "")
    value = norm_value(line.value or "")
    if not (category and footprint and value):
        return None
    pool = db.scalars(select(Item).where(Item.user_id == user_id, Item.category == category)).all()
    for item in pool:
        if footprint_main(item.footprint or "") == footprint and norm_value(item.value or "") == value:
            return item
    return None


def _library_suggestions(item: Item, box_name: str) -> dict:
    record = {
        "item_id": item.id,
        "lcsc_code": item.lcsc_code or "",
        "mpn": item.mpn or "",
        "name": item.name or "",
        "footprint": item.footprint or "",
        "value": item.value or "",
        "category": item.category or "",
        "quantity": item.quantity or 0,
        "box_name": box_name or "",
        "row": item.row,
        "col": item.col,
        "suitable": True,
        "reason": "已在物料库",
        "risks": [],
    }
    return {"source": "library", "reason": "已在物料库", "risks": [], "exact_hits": [record], "candidates": []}


def _link_line(line: ProjectLine, item: Item, box_name: str) -> None:
    line.matched_item_id = item.id
    line.match_status = "insufficient" if (item.quantity or 0) < (line.quantity_required or 0) else "matched"
    line.suggestions_json = json.dumps(_library_suggestions(item, box_name), ensure_ascii=False)
    line.matched_at = utcnow()


def _use_item_on_line(line: ProjectLine, item: Item, box_name: str) -> None:
    before = item.quantity
    line.lcsc_code = item.lcsc_code or ""
    line.mpn = item.mpn or ""
    line.brand = item.brand or ""
    line.footprint = item.footprint or ""
    line.value = item.value or ""
    line.params = item.params or ""
    line.product_name = item.name or ""
    line.category = item.category or ""
    _link_line(line, item, box_name)
    item.quantity = before
    suggestions = json.loads(line.suggestions_json or "{}")
    suggestions["reason"] = ""
    for record in suggestions.get("exact_hits") or []:
        if isinstance(record, dict):
            record["reason"] = ""
    line.suggestions_json = json.dumps(suggestions, ensure_ascii=False)


def _patch_stock(line: ProjectLine, item: Item) -> None:
    try:
        suggestions = json.loads(line.suggestions_json or "{}")
    except json.JSONDecodeError:
        suggestions = {}
    if not isinstance(suggestions, dict):
        suggestions = {}
    for key in ("exact_hits", "candidates"):
        records = suggestions.get(key) or []
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and record.get("item_id") == item.id:
                record["quantity"] = item.quantity or 0
    line.suggestions_json = json.dumps(suggestions, ensure_ascii=False)
    if line.match_status in ("matched", "insufficient"):
        line.match_status = "insufficient" if (item.quantity or 0) < (line.quantity_required or 0) else "matched"


def _box_name(db: Session, item: Item) -> str:
    if not item.box_id:
        return ""
    return db.scalar(select(Box.name).where(Box.id == item.box_id)) or ""


def _own_line(db: Session, project: Project, line_id: int) -> ProjectLine:
    line = db.scalar(select(ProjectLine).where(ProjectLine.id == line_id, ProjectLine.project_id == project.id))
    if line is None:
        raise HTTPException(status_code=404, detail="明细不存在")
    return line


def _own_project(db: Session, user: User, project_id: int) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("", response_model=list[ProjectBrief])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ProjectBrief]:
    rows = db.execute(
        select(Project, func.count(ProjectLine.id))
        .outerjoin(ProjectLine, ProjectLine.project_id == Project.id)
        .where(Project.user_id == user.id)
        .group_by(Project.id)
        .order_by(Project.id.desc())
    ).all()
    return [
        ProjectBrief(
            id=project.id,
            name=project.name,
            source_filename=project.source_filename,
            format=project.format,
            purchase_sets=project.purchase_sets,
            order_no=project.order_no or "",
            imported_at=project.imported_at,
            line_count=count,
        )
        for project, count in rows
    ]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProjectOut:
    return project_out(db, _own_project(db, user, project_id))


@router.delete("/{project_id}")
def delete_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    project = _own_project(db, user, project_id)
    db.execute(delete(ProjectLine).where(ProjectLine.project_id == project.id))
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/import", response_model=ProjectOut)
def import_project(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    filename = Path(file.filename or "").name
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="请上传文件")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 10MB")
    try:
        parsed = parse_upload(filename, data)
    except BomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _enrich_lines(parsed.lines, load_catalog(db, user.id))
    project = Project(
        user_id=user.id,
        name=parsed.name,
        source_filename=filename,
        format=parsed.format,
        purchase_sets=parsed.purchase_sets,
        order_no=parsed.order_no,
    )
    db.add(project)
    db.flush()
    for line in parsed.lines:
        db.add(
            ProjectLine(
                project_id=project.id,
                line_no=line.line_no,
                designators=line.designators,
                quantity_per_board=line.quantity_per_board,
                quantity_required=line.quantity_required,
                lcsc_code=line.lcsc_code,
                mpn=line.mpn,
                brand=line.brand,
                footprint=line.footprint,
                value=line.value,
                params=line.params,
                product_name=line.product_name,
                category=line.category,
            )
        )
    db.flush()
    apply_match(db, user.id, project)
    db.commit()
    db.refresh(project)
    return project_out(db, project)


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = _own_project(db, user, project_id)
    project.purchase_sets = body.purchase_sets
    apply_match(db, user.id, project)
    db.commit()
    return project_out(db, project)


@router.get("/{project_id}/recommend")
async def recommend(project_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_project(db, user, project_id)
    db.commit()
    updates: queue.Queue = queue.Queue()
    run = AiRun()

    def emit(line: ProjectLine) -> None:
        updates.put(line_out(line).model_dump(mode="json"))

    def worker() -> None:
        try:
            recommend_pending(project_id, user.id, run, emit)
        finally:
            updates.put(None)

    threading.Thread(target=worker, daemon=True).start()

    async def events():
        try:
            while True:
                if await request.is_disconnected():
                    run.stop()
                    break
                try:
                    item = updates.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.2)
                    continue
                if item is None:
                    yield "event: done\ndata: {}\n\n"
                    break
                yield "event: line\ndata: " + json.dumps(item, ensure_ascii=False) + "\n\n"
        finally:
            run.stop()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/match", response_model=ProjectOut)
def rematch(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProjectOut:
    project = _own_project(db, user, project_id)
    apply_match(db, user.id, project)
    db.commit()
    return project_out(db, project)


@router.post("/{project_id}/add-all", response_model=BulkAddOut)
def add_all(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BulkAddOut:
    project = _own_project(db, user, project_id)
    lines = db.scalars(select(ProjectLine).where(ProjectLine.project_id == project.id).order_by(ProjectLine.id)).all()
    added = 0
    incremented = 0
    for line in lines:
        item = _find_lib_item(db, user.id, line)
        amount = line.quantity_required or 0
        if item is None:
            code = (line.lcsc_code or "").strip() or None
            item = Item(
                user_id=user.id,
                lcsc_code=code,
                mpn=line.mpn or "",
                name=line.product_name or "",
                brand=line.brand or "",
                footprint=line.footprint or "",
                category=line.category or "",
                value=line.value or "",
                params=line.params or "",
                specs="{}",
                quantity=amount,
            )
            db.add(item)
            db.flush()
            added += 1
        else:
            item.quantity = (item.quantity or 0) + amount
            item.updated_at = utcnow()
            incremented += 1
        line.matched_item_id = item.id
    for line in lines:
        item = db.get(Item, line.matched_item_id) if line.matched_item_id else None
        if item is not None:
            _link_line(line, item, _box_name(db, item))
    db.commit()
    return BulkAddOut(added=added, incremented=incremented)


@router.post("/{project_id}/checkout", response_model=CheckoutOut)
def checkout(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CheckoutOut:
    project = _own_project(db, user, project_id)
    lines = db.scalars(select(ProjectLine).where(ProjectLine.project_id == project.id)).all()
    totals: dict[int, int] = {}
    linked: list[ProjectLine] = []
    skipped = 0
    for line in lines:
        if not line.matched_item_id:
            skipped += 1
            continue
        linked.append(line)
        totals[line.matched_item_id] = totals.get(line.matched_item_id, 0) + (line.quantity_required or 0)
    items = {
        item.id: item
        for item in db.scalars(select(Item).where(Item.user_id == user.id, Item.id.in_(totals))).all()
    } if totals else {}
    deducted = 0
    for line in linked:
        item = items.get(line.matched_item_id)
        if item is None:
            skipped += 1
            continue
        deducted += 1
    for item_id, amount in totals.items():
        item = items.get(item_id)
        if item is None:
            continue
        item.quantity = (item.quantity or 0) - amount
        item.updated_at = utcnow()
    for line in linked:
        item = items.get(line.matched_item_id)
        if item is not None:
            _patch_stock(line, item)
    db.commit()
    return CheckoutOut(deducted=deducted, skipped=skipped)


@router.post("/{project_id}/lines/{line_id}/replace", response_model=LineOut)
def replace_line(
    project_id: int,
    line_id: int,
    body: ReplaceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LineOut:
    project = _own_project(db, user, project_id)
    line = _own_line(db, project, line_id)
    item = None
    if body.item_id is not None:
        item = db.scalar(select(Item).where(Item.id == body.item_id, Item.user_id == user.id))
        if item is None:
            raise HTTPException(status_code=404, detail="库存物料不存在")
    else:
        code = (body.lcsc_code or "").strip()
        if not code:
            raise HTTPException(status_code=400, detail="请选择库中物料或填写立创编号")
        catalog = load_catalog(db, user.id)
        item = db.scalar(select(Item).where(Item.user_id == user.id, func.lower(Item.lcsc_code) == code.lower()))
        if item is None:
            try:
                info = fetch_lcsc(code, catalog)
            except LcscError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            item = Item(
                user_id=user.id,
                lcsc_code=(info.get("lcsc_code") or code).strip() or None,
                mpn=info.get("mpn") or "",
                name=info.get("name") or "",
                brand=info.get("brand") or "",
                footprint=info.get("footprint") or "",
                category=info.get("category") or "",
                value=info.get("value") or "",
                params=info.get("params") or "",
                specs=dump_specs(catalog.extract(info.get("category") or "", parse_params(info.get("params") or ""))),
                datasheet_url=info.get("datasheet_url") or "",
                quantity=0,
            )
            db.add(item)
            db.flush()
    quantity_before = item.quantity
    _use_item_on_line(line, item, _box_name(db, item))
    item.quantity = quantity_before
    db.commit()
    return line_out(line)


@router.post("/{project_id}/lines/{line_id}/accept", response_model=LineOut)
def accept_line(
    project_id: int,
    line_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LineOut:
    project = _own_project(db, user, project_id)
    line = _own_line(db, project, line_id)
    if line.match_status != "suggested" or not line.matched_item_id:
        raise HTTPException(status_code=400, detail="这条明细没有可使用的替换器件")
    item = db.scalar(select(Item).where(Item.id == line.matched_item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=400, detail="替换器件不在物料库中")
    line.match_status = "insufficient" if (item.quantity or 0) < (line.quantity_required or 0) else "matched"
    line.matched_at = utcnow()
    db.commit()
    return line_out(line)


@router.post("/{project_id}/lines/{line_id}/stock-delta", response_model=LineOut)
def stock_delta(
    project_id: int,
    line_id: int,
    body: StockDeltaIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LineOut:
    project = _own_project(db, user, project_id)
    line = _own_line(db, project, line_id)
    if not line.matched_item_id:
        raise HTTPException(status_code=400, detail="这条明细还没有对应的库存物料")
    item = db.scalar(select(Item).where(Item.id == line.matched_item_id, Item.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=400, detail="库存物料不存在")
    item.quantity = (item.quantity or 0) + body.delta
    item.updated_at = utcnow()
    _patch_stock(line, item)
    db.commit()
    return line_out(line)


@router.post("/{project_id}/lines/{line_id}/adopt", response_model=AdoptOut)
def adopt_line(
    project_id: int,
    line_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdoptOut:
    project = _own_project(db, user, project_id)
    line = db.scalar(select(ProjectLine).where(ProjectLine.id == line_id, ProjectLine.project_id == project.id))
    if line is None:
        raise HTTPException(status_code=404, detail="明细不存在")
    if not (line.lcsc_code or "").strip():
        raise HTTPException(status_code=400, detail="该明细没有立创编号")
    catalog = load_catalog(db, user.id)
    warning = ""
    try:
        info = fetch_lcsc(line.lcsc_code, catalog)
    except LcscError:
        info = {
            "lcsc_code": line.lcsc_code,
            "mpn": line.mpn,
            "name": line.product_name,
            "brand": line.brand,
            "footprint": line.footprint,
            "category": line.category,
            "value": line.value,
            "params": line.params,
            "specs": catalog.extract(line.category or "", parse_params(line.params or "")),
            "datasheet_url": "",
            "image_url": "",
            "mall_stock": None,
            "mall_price": "",
        }
        warning = "立创查询失败，已用 BOM 中的字段预填，请核对后手填"
    return AdoptOut(
        lcsc_code=info.get("lcsc_code") or line.lcsc_code,
        mpn=info.get("mpn") or "",
        name=info.get("name") or "",
        brand=info.get("brand") or "",
        footprint=info.get("footprint") or "",
        category=info.get("category") or "",
        value=info.get("value") or "",
        params=info.get("params") or "",
        specs=info.get("specs") or {},
        datasheet_url=info.get("datasheet_url") or "",
        image_url=info.get("image_url") or "",
        quantity=0,
        mall_stock=info.get("mall_stock"),
        mall_price=info.get("mall_price") or "",
        warning=warning,
    )
