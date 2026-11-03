from __future__ import annotations

import os
import tempfile
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import app.database as database
from app.database import get_db
from app.deps import require_admin
from app.models import User
from app.routers.auth import clear_session
from app.schemas import AiTestIn, AiTestOut, SystemSettingsIn, SystemSettingsOut
from app.services.backup import BackupError, build_backup
from app.services.deepseek import AiChatError, chat
from app.services.system_config import (
    DatabaseSwitchError,
    SystemSettings,
    mask_key,
    normalize_ai,
    read_settings,
    switch_database,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _out(settings: SystemSettings, switched: bool = False) -> SystemSettingsOut:
    return SystemSettingsOut(
        database_location=settings.database_location,
        database_name=settings.database_name,
        deepseek_api_key=mask_key(settings.deepseek_api_key),
        deepseek_api_key_set=bool(settings.deepseek_api_key),
        deepseek_base_url=settings.deepseek_base_url,
        deepseek_model=settings.deepseek_model,
        allow_register=settings.allow_register,
        database_switched=switched,
    )


def _stored_key(db: Session) -> str:
    try:
        return read_settings(db).deepseek_api_key
    except DatabaseSwitchError:
        return ""


def _resolve_key(incoming: str, stored: str) -> str:
    text = (incoming or "").strip()
    if stored and text == mask_key(stored):
        return stored
    return text


@router.get("", response_model=SystemSettingsOut)
def get_system_settings(_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> SystemSettingsOut:
    try:
        return _out(read_settings(db))
    except DatabaseSwitchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("", response_model=SystemSettingsOut)
def update_system_settings(
    body: SystemSettingsIn,
    response: Response,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SystemSettingsOut:
    try:
        current = read_settings(db)
        stored, switched = switch_database(
            SystemSettings(
                database_location=body.database_location,
                database_name=body.database_name,
                deepseek_api_key=_resolve_key(body.deepseek_api_key, current.deepseek_api_key),
                deepseek_base_url=body.deepseek_base_url,
                deepseek_model=body.deepseek_model,
                allow_register=current.allow_register if body.allow_register is None else body.allow_register,
            ),
            db,
        )
    except DatabaseSwitchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if switched:
        clear_session(response)
    return _out(stored, switched)


@router.post("/ai-test", response_model=AiTestOut)
def test_ai(body: AiTestIn, _user: User = Depends(require_admin), db: Session = Depends(get_db)) -> AiTestOut:
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="请输入要发送的内容")
    if len(prompt) > 4000:
        raise HTTPException(status_code=400, detail="测试内容不能超过 4000 字")
    try:
        api_key, base_url, model = normalize_ai(
            _resolve_key(body.deepseek_api_key, _stored_key(db)), body.deepseek_base_url, body.deepseek_model
        )
    except DatabaseSwitchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")
    try:
        output = chat(prompt, api_key=api_key, base_url=base_url, model=model)
    except AiChatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AiTestOut(output=output)


@router.get("/backup")
def download_backup(background: BackgroundTasks, _user: User = Depends(require_admin)) -> FileResponse:
    handle, raw = tempfile.mkstemp(suffix=".zip", prefix="cms-backup-")
    os.close(handle)
    try:
        build_backup(database.current_url, raw)
    except BackupError as exc:
        os.unlink(raw)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        os.unlink(raw)
        raise
    background.add_task(os.unlink, raw)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return FileResponse(raw, media_type="application/zip", filename=f"component-backup-{stamp}.zip")
