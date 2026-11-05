"""按立创编号在后台补全物料资料。

同一进程同时只访问一次立创。上一次结束后再随机等待，并且任意 60 秒内不超过 30 次，
避免固定频率把这台机器的地址打成爬虫。
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

import app.database as database
from app.models import Item, utcnow
from app.services.images import assign_image
from app.services.lcsc import fetch_lcsc
from app.services.spec_config import load_catalog
from app.services.specs import SpecCatalog, dump_specs

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
FAILED = "failed"
IDLE = "idle"
BUSY_STATES = (QUEUED, RUNNING)
BUSY_DETAIL = "该物料正在从立创更新资料，完成前不能查询或编辑"
RATE_DETAIL = "立创查询过于频繁，请稍后再试"

MAX_PER_MINUTE = 30
WINDOW_SECONDS = 60.0
GAP_MIN = 2.0
GAP_MAX = 3.6
MANUAL_MAX_WAIT = 4.0


class RequestPacer:
    """串行访问立创：在途请求只有一个，结束后再随机间隔，并卡住每分钟 30 次的上限。"""

    def __init__(
        self,
        *,
        limit: int = MAX_PER_MINUTE,
        window: float = WINDOW_SECONDS,
        gap_min: float = GAP_MIN,
        gap_max: float = GAP_MAX,
        rng: random.Random | None = None,
        clock=None,
    ) -> None:
        self.limit = limit
        self.window = window
        self.gap_min = gap_min
        self.gap_max = gap_max
        self.rng = rng or random.Random()
        self._clock = clock or time.monotonic
        self.starts: deque[float] = deque()
        self.ready_at: float | None = None
        self.in_flight = False
        self.cv = threading.Condition()

    def seconds_until(self, now: float) -> float:
        while self.starts and now - self.starts[0] >= self.window:
            self.starts.popleft()
        wait = 0.0
        if len(self.starts) >= self.limit:
            wait = self.window - (now - self.starts[0])
        if self.ready_at is not None:
            wait = max(wait, self.ready_at - now)
        return max(0.0, wait)

    def acquire(self, *, stop: threading.Event | None = None, max_wait: float | None = None) -> bool:
        started = self._clock()
        with self.cv:
            while True:
                if stop is not None and stop.is_set():
                    return False
                now = self._clock()
                delay = self.seconds_until(now)
                if self.in_flight:
                    delay = max(delay, 0.2)
                if delay <= 0:
                    self.in_flight = True
                    self.starts.append(now)
                    return True
                if max_wait is not None and (now - started) + delay > max_wait:
                    return False
                timeout = min(delay, 0.25)
                if max_wait is not None:
                    remain = max_wait - (now - started)
                    if remain <= 0:
                        return False
                    timeout = min(timeout, remain)
                self.cv.wait(timeout)

    def release(self) -> None:
        with self.cv:
            if not self.in_flight:
                return
            self.in_flight = False
            self.ready_at = self._clock() + self.rng.uniform(self.gap_min, self.gap_max)
            self.cv.notify_all()


PACER = RequestPacer()

_stop = threading.Event()
_wake = threading.Event()
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


@dataclass
class RefreshResult:
    queued: int = 0
    skipped_busy: int = 0
    skipped_no_code: int = 0
    pending_codes: list[str] = field(default_factory=list)
    queued_codes: list[str] = field(default_factory=list)


def is_refresh_busy(db: Session, user_id: int, *, item_id: int | None = None, code: str | None = None) -> bool:
    if item_id is not None:
        status = db.scalar(select(Item.lcsc_sync_status).where(Item.id == item_id, Item.user_id == user_id))
        if status in BUSY_STATES:
            return True
    text = (code or "").strip().upper()
    if not text:
        return False
    found = db.scalar(
        select(Item.id).where(
            Item.user_id == user_id,
            Item.lcsc_code == text,
            Item.lcsc_sync_status.in_(BUSY_STATES),
        )
    )
    return found is not None


def refresh_counts(db: Session, user_id: int) -> dict[str, int]:
    rows = db.execute(
        select(Item.lcsc_sync_status, func.count())
        .where(Item.user_id == user_id)
        .group_by(Item.lcsc_sync_status)
    ).all()
    output = {"queued": 0, "running": 0, "failed": 0}
    for status, count in rows:
        if status in output:
            output[status] = int(count)
    return output


def queue_items(
    db: Session,
    user_id: int,
    *,
    item_ids: list[int] | None = None,
    lcsc_codes: list[str] | None = None,
    all_items: bool = False,
) -> RefreshResult:
    filters = [Item.user_id == user_id]
    if all_items:
        filters.append(Item.lcsc_code.is_not(None))
        filters.append(Item.lcsc_code != "")
    elif item_ids is not None:
        if not item_ids:
            return RefreshResult()
        filters.append(Item.id.in_(item_ids))
    elif lcsc_codes is not None:
        if not lcsc_codes:
            return RefreshResult()
        filters.append(Item.lcsc_code.in_(lcsc_codes))
    else:
        raise ValueError("请指定要更新的物料")

    items = list(db.scalars(select(Item).where(*filters)).all())
    result = RefreshResult()
    found: set[str] = set()
    now = utcnow()
    for item in items:
        code = (item.lcsc_code or "").strip().upper()
        if code:
            found.add(code)
        if not code:
            result.skipped_no_code += 1
            continue
        if (item.lcsc_sync_status or "") in BUSY_STATES:
            result.skipped_busy += 1
            continue
        item.lcsc_sync_status = QUEUED
        item.lcsc_sync_error = ""
        item.lcsc_sync_at = now
        result.queued += 1
        if lcsc_codes is not None:
            result.queued_codes.append(code)
    if lcsc_codes is not None:
        result.pending_codes = [code for code in lcsc_codes if code not in found]
    return result


def kick_refresh() -> None:
    _wake.set()


def _clip(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _apply_product(item: Item, info: dict, catalog: SpecCatalog) -> None:
    item.mpn = _clip(info.get("mpn"), 255)
    item.name = _clip(info.get("name"), 255)
    item.brand = _clip(info.get("brand"), 255)
    item.footprint = _clip(info.get("footprint"), 255)
    item.category = _clip(info.get("category"), 255)
    item.value = _clip(info.get("value"), 255)
    item.params = str(info.get("params") or "")
    specs = info.get("specs") if isinstance(info.get("specs"), dict) else {}
    item.specs = dump_specs(catalog.clean(item.category, specs, strict=False))
    item.datasheet_url = str(info.get("datasheet_url") or "")
    price = info.get("unit_price")
    if item.unit_price is None and isinstance(price, (int, float)) and not isinstance(price, bool):
        item.unit_price = float(price)
    assign_image(item, str(info.get("image_url") or ""))
    item.updated_at = utcnow()


def _mark(item_id: int, status: str, error: str) -> None:
    db = database.SessionLocal()
    try:
        item = db.get(Item, item_id)
        if item is None or item.lcsc_sync_status == IDLE:
            return
        item.lcsc_sync_status = status
        item.lcsc_sync_error = (error or "")[:300]
        db.commit()
    except Exception:
        logger.exception("记录立创更新状态失败")
        db.rollback()
    finally:
        db.close()


def perform_refresh(item_id: int) -> None:
    db = database.SessionLocal()
    code = ""
    user_id = 0
    catalog: SpecCatalog | None = None
    try:
        item = db.get(Item, item_id)
        if item is None or item.lcsc_sync_status != QUEUED:
            return
        code = (item.lcsc_code or "").strip().upper()
        user_id = item.user_id
        if not code:
            item.lcsc_sync_status = FAILED
            item.lcsc_sync_error = "没有立创编号"
            db.commit()
            return
        item.lcsc_sync_status = RUNNING
        item.lcsc_sync_error = ""
        db.commit()
        catalog = load_catalog(db, user_id)
    finally:
        db.close()

    if catalog is None or not code:
        return
    try:
        info = fetch_lcsc(code, catalog, user_id=user_id)
    except Exception:
        logger.warning("立创资料更新失败 item=%s code=%s", item_id, code, exc_info=True)
        _mark(item_id, FAILED, "立创查询失败，可稍后重试")
        return

    db = database.SessionLocal()
    try:
        item = db.get(Item, item_id)
        if item is None or item.lcsc_sync_status != RUNNING:
            return
        _apply_product(item, info, catalog)
        item.lcsc_sync_status = IDLE
        item.lcsc_sync_error = ""
        db.commit()
    except Exception:
        logger.exception("写入立创资料失败 item=%s", item_id)
        db.rollback()
        _mark(item_id, FAILED, "写入资料失败，可稍后重试")
    finally:
        db.close()


def _session():
    return database.SessionLocal()


def _requeue_running() -> None:
    db = _session()
    try:
        db.execute(update(Item).where(Item.lcsc_sync_status == RUNNING).values(lcsc_sync_status=QUEUED))
        db.commit()
    except Exception:
        logger.exception("恢复中断的立创更新失败")
        db.rollback()
    finally:
        db.close()


def _next_queued_id() -> int | None:
    db = _session()
    try:
        return db.scalar(
            select(Item.id)
            .where(Item.lcsc_sync_status == QUEUED)
            .order_by(Item.lcsc_sync_at.asc(), Item.id.asc())
            .limit(1)
        )
    finally:
        db.close()


def _loop() -> None:
    _requeue_running()
    while not _stop.is_set():
        if _next_queued_id() is None:
            _wake.wait(1.5)
            _wake.clear()
            continue
        if not PACER.acquire(stop=_stop):
            return
        current: int | None = None
        try:
            current = _next_queued_id()
            if current is not None:
                perform_refresh(current)
        except Exception:
            logger.exception("立创资料更新中断")
            if current is not None:
                _mark(current, FAILED, "立创查询失败，可稍后重试")
        finally:
            PACER.release()


def start_worker() -> None:
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="lcsc-refresh", daemon=True)
        _thread.start()


def stop_worker() -> None:
    _stop.set()
    _wake.set()
    with PACER.cv:
        PACER.cv.notify_all()
    thread = _thread
    if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
        thread.join(timeout=5)
