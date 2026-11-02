from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Item, StockEvent, User
from app.schemas import StatPoint, StatSeries

router = APIRouter(prefix="/api/statistics", tags=["statistics"])

CST = timezone(timedelta(hours=8))


def _day(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CST).date()


def _range(start: date | None, end: date | None, days: int) -> tuple[date, date]:
    today = datetime.now(CST).date()
    finish = end or today
    begin = start or (finish - timedelta(days=max(days, 1) - 1))
    if begin > finish:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    if (finish - begin).days > 366:
        raise HTTPException(status_code=400, detail="时间范围不能超过一年")
    return begin, finish


def _events(db: Session, user: User) -> list[StockEvent]:
    return list(db.scalars(select(StockEvent).where(StockEvent.user_id == user.id)).all())


def _items(db: Session, user: User) -> list[Item]:
    return list(db.scalars(select(Item).where(Item.user_id == user.id)).all())


def _dates(begin: date, finish: date) -> list[date]:
    days = []
    cursor = begin
    while cursor <= finish:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _series(begin: date, finish: date, values: dict[date, float]) -> StatSeries:
    return StatSeries(
        start=begin.isoformat(),
        end=finish.isoformat(),
        points=[StatPoint(date=day.isoformat(), value=values[day]) for day in _dates(begin, finish)],
    )


@router.get("/value-trend", response_model=StatSeries)
def value_trend(
    start: date | None = None,
    end: date | None = None,
    days: int = Query(30, ge=1, le=366),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatSeries:
    begin, finish = _range(start, end, days)
    return _series(begin, finish, _reconstruct(db, user, begin, finish, priced=True))


@router.get("/count-trend", response_model=StatSeries)
def count_trend(
    start: date | None = None,
    end: date | None = None,
    days: int = Query(30, ge=1, le=366),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatSeries:
    begin, finish = _range(start, end, days)
    return _series(begin, finish, _reconstruct(db, user, begin, finish, priced=False))


@router.get("/consumption", response_model=StatSeries)
def consumption(
    start: date | None = None,
    end: date | None = None,
    days: int = Query(30, ge=1, le=366),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatSeries:
    begin, finish = _range(start, end, days)
    totals: dict[date, float] = defaultdict(float)
    for event in _events(db, user):
        if event.event_type != "checkout" or (event.quantity_delta or 0) >= 0:
            continue
        day = _day(event.created_at)
        if begin <= day <= finish:
            totals[day] += -event.quantity_delta
    values = {day: float(totals.get(day, 0)) for day in _dates(begin, finish)}
    return _series(begin, finish, values)


def _reconstruct(db: Session, user: User, begin: date, finish: date, *, priced: bool) -> dict[date, float]:
    items = _items(db, user)
    current = {item.id: item.quantity or 0 for item in items}
    prices = {item.id: float(item.unit_price or 0) for item in items}
    later: dict[int, list[tuple[date, int]]] = defaultdict(list)
    for event in _events(db, user):
        later[event.item_id].append((_day(event.created_at), event.quantity_delta or 0))
    item_ids = set(current) | set(later)
    values: dict[date, float] = {}
    for day in _dates(begin, finish):
        total = 0.0
        for item_id in item_ids:
            quantity = current.get(item_id, 0) - sum(delta for event_day, delta in later.get(item_id, []) if event_day > day)
            if priced:
                total += quantity * prices.get(item_id, 0)
            else:
                total += quantity
        values[day] = round(total, 4) if priced else float(total)
    return values
