from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import User
from app.schemas import AiTestIn, AiTestOut, SystemSettingsIn, SystemSettingsOut
from app.services.deepseek import AiChatError, chat
from app.services.system_config import DatabaseSwitchError, SystemSettings, normalize_ai, read_settings, switch_database

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _out(settings: SystemSettings) -> SystemSettingsOut:
    return SystemSettingsOut(
        database_location=settings.database_location,
        database_name=settings.database_name,
        deepseek_api_key=settings.deepseek_api_key,
        deepseek_base_url=settings.deepseek_base_url,
        deepseek_model=settings.deepseek_model,
    )


@router.get("", response_model=SystemSettingsOut)
def get_system_settings(_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> SystemSettingsOut:
    return _out(read_settings(db))


@router.put("", response_model=SystemSettingsOut)
def update_system_settings(
    body: SystemSettingsIn,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SystemSettingsOut:
    try:
        stored = switch_database(
            SystemSettings(
                database_location=body.database_location,
                database_name=body.database_name,
                deepseek_api_key=body.deepseek_api_key,
                deepseek_base_url=body.deepseek_base_url,
                deepseek_model=body.deepseek_model,
            ),
            db,
        )
    except DatabaseSwitchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(stored)


@router.post("/ai-test", response_model=AiTestOut)
def test_ai(body: AiTestIn, _user: User = Depends(require_admin)) -> AiTestOut:
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="请输入要发送的内容")
    if len(prompt) > 4000:
        raise HTTPException(status_code=400, detail="测试内容不能超过 4000 字")
    try:
        api_key, base_url, model = normalize_ai(body.deepseek_api_key, body.deepseek_base_url, body.deepseek_model)
    except DatabaseSwitchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")
    try:
        output = chat(prompt, api_key=api_key, base_url=base_url, model=model)
    except AiChatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AiTestOut(output=output)
