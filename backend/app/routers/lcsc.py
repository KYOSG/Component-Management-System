from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.lcsc import LcscError, fetch_lcsc
from app.services.lcsc_refresh import BUSY_DETAIL, MANUAL_MAX_WAIT, PACER, RATE_DETAIL, is_refresh_busy
from app.services.spec_config import load_catalog

router = APIRouter(prefix="/api/lcsc", tags=["lcsc"])


@router.get("/{code}")
def query_product(
    code: str,
    item_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    product_code = (code or "").strip().upper()
    if not product_code:
        raise HTTPException(status_code=400, detail="查询失败，请手填")
    if is_refresh_busy(db, user.id, item_id=item_id, code=product_code):
        raise HTTPException(status_code=409, detail=BUSY_DETAIL)
    if not PACER.acquire(max_wait=MANUAL_MAX_WAIT):
        raise HTTPException(status_code=429, detail=RATE_DETAIL)
    try:
        return fetch_lcsc(product_code, load_catalog(db, user.id), user_id=user.id)
    except LcscError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        PACER.release()
