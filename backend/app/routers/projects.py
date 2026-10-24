from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Project, ProjectLine, User
from app.schemas import AdoptOut, LineOut, ProjectBrief, ProjectOut, ProjectUpdate
from app.services.bom import BomError, parse_upload
from app.services.lcsc import LcscError, fetch_lcsc
from app.services.matching import apply_match
from app.services.system_config import read_settings
from app.services.specs import specs_from_params

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _location(record: dict) -> str:
    label = record.get("mpn") or record.get("lcsc_code") or record.get("name") or "物料"
    if record.get("box_name") and record.get("row") and record.get("col"):
        place = f"{record['box_name']} 第{record['row']}行第{record['col']}列"
    else:
        place = "未入盒"
    return f"{label} · {place}（库存 {record.get('quantity', 0)}）"


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
        reason=suggestions.get("reason") or "",
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
        lines=[line_out(line, include_match=ai_enabled) for line in lines],
    )


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


@router.post("/import", response_model=ProjectOut)
async def import_project(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    filename = Path(file.filename or "").name
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="请上传文件")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 10MB")
    try:
        parsed = parse_upload(filename, data)
    except BomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.post("/{project_id}/match", response_model=ProjectOut)
def rematch(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProjectOut:
    project = _own_project(db, user, project_id)
    apply_match(db, user.id, project)
    db.commit()
    return project_out(db, project)


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
    warning = ""
    try:
        info = fetch_lcsc(line.lcsc_code)
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
            "specs": specs_from_params(line.category or "", line.params or ""),
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
