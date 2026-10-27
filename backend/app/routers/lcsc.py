from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.lcsc import LcscError, fetch_lcsc
from app.services.spec_config import load_catalog

router = APIRouter(prefix="/api/lcsc", tags=["lcsc"])


@router.get("/{code}")
def query_product(code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        return fetch_lcsc(code, load_catalog(db, user.id))
    except LcscError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
