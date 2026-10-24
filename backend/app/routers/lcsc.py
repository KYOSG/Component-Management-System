from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_current_user
from app.models import User
from app.services.lcsc import LcscError, fetch_lcsc

router = APIRouter(prefix="/api/lcsc", tags=["lcsc"])


@router.get("/{code}")
def query_product(code: str, _: User = Depends(get_current_user)) -> dict:
    try:
        return fetch_lcsc(code)
    except LcscError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
