from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.routers.items import present_item, raise_stock
from app.schemas import ItemOut, TransferIn
from app.services.spec_config import load_catalog
from app.services.stock import StockError, transfer

router = APIRouter(tags=["transfer"])


@router.post("/api/transfer", response_model=ItemOut)
def transfer_stock(
    body: TransferIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ItemOut:
    try:
        item = transfer(
            db,
            user.id,
            from_location_id=body.from_location_id,
            to_type=body.to_type,
            to_box_id=body.to_box_id,
            to_row=body.to_row,
            to_col=body.to_col,
            to_slot_index=body.to_slot_index,
            quantity=body.quantity,
        )
    except StockError as exc:
        raise_stock(exc)
    db.commit()
    db.refresh(item)
    return present_item(db, item, load_catalog(db, user.id))
