from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.database as database
from app.database import sqlite_path
from app.models import Item

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
FILENAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}\.(jpg|png|webp|gif)$")


def image_dir(database_url: str | None = None) -> Path:
    chosen = database.current_url if database_url is None else database_url
    path = sqlite_path(chosen)
    root = (path.parent if path is not None else Path("data")) / "images"
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_remote(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def is_local(url: str) -> bool:
    return url.startswith("/api/media/")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", value or "")[:60]
    return cleaned


def media_name(url: str) -> str:
    return Path(url).name


def display_image_url(url: str) -> str:
    text = (url or "").strip()
    if not is_local(text):
        return ""
    name = media_name(text)
    if FILENAME_RE.fullmatch(name) is None:
        return ""
    if not (image_dir() / name).is_file():
        return ""
    return f"/api/media/{name}"


def stem_for(item_id: int, lcsc_code: str | None) -> str:
    code = safe_stem(lcsc_code or "")
    if code:
        return f"lcsc-{code}"
    return f"item-{item_id}"


def find_file(stem: str, database_url: str | None = None) -> Path | None:
    folder = image_dir(database_url)
    for ext in (".jpg", ".png", ".webp", ".gif"):
        path = folder / f"{stem}{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def localize(url: str, stem: str, *, refresh: bool = False, database_url: str | None = None) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if is_local(text):
        name = media_name(text)
        if FILENAME_RE.fullmatch(name) and (image_dir(database_url) / name).is_file():
            return f"/api/media/{name}"
        return ""
    if not is_remote(text):
        return ""
    existing = find_file(stem, database_url)
    if existing is not None and not refresh:
        return f"/api/media/{existing.name}"
    saved = _download(text, stem, database_url)
    if saved is not None:
        return f"/api/media/{saved.name}"
    if existing is not None:
        return f"/api/media/{existing.name}"
    return ""


def assign_image(item: Item, incoming: str) -> None:
    text = (incoming or "").strip()
    previous = item.image_url or ""
    if not text:
        if is_remote(previous):
            local = localize(previous, stem_for(item.id, item.lcsc_code))
            item.image_url = local or previous
            return
        _delete_item_file(item.id, previous)
        item.image_url = ""
        return
    if is_local(text):
        local = localize(text, stem_for(item.id, item.lcsc_code))
        if local:
            if previous.startswith(f"/api/media/item-{item.id}.") and previous != local:
                _delete_item_file(item.id, previous)
            item.image_url = local
            return
        item.image_url = display_image_url(previous)
        return
    if is_remote(text):
        local = localize(text, stem_for(item.id, item.lcsc_code), refresh=True)
        if local:
            if previous.startswith(f"/api/media/item-{item.id}.") and previous != local:
                _delete_item_file(item.id, previous)
            item.image_url = local
            return
        item.image_url = display_image_url(previous)
        return
    item.image_url = display_image_url(previous)


def delete_item_image(item: Item) -> None:
    _delete_item_file(item.id, item.image_url or "")


def cache_remote_item_images(session_factory, database_url: str) -> None:
    db: Session = session_factory()
    try:
        items = db.scalars(select(Item)).all()
        changed = False
        for item in items:
            url = item.image_url or ""
            if not is_remote(url):
                continue
            local = localize(url, stem_for(item.id, item.lcsc_code), database_url=database_url)
            if local:
                item.image_url = local
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def _download(url: str, stem: str, database_url: str | None) -> Path | None:
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            content = response.content
            content_type = response.headers.get("content-type", "")
    except Exception as exc:
        logger.warning("物料图片下载失败：%s", exc)
        return None
    if not content or len(content) > MAX_BYTES:
        logger.warning("物料图片为空或超过 5MB")
        return None
    ext = EXTENSIONS.get(content_type.split(";", 1)[0].strip().lower()) or _sniff(content)
    if ext is None:
        logger.warning("物料图片格式无法识别")
        return None
    folder = image_dir(database_url)
    for old in folder.glob(f"{stem}.*"):
        if old.suffix.lower() in {".jpg", ".png", ".webp", ".gif"} and old.suffix.lower() != ext:
            old.unlink(missing_ok=True)
    target = folder / f"{stem}{ext}"
    temporary = folder / f"{stem}{ext}.tmp"
    temporary.write_bytes(content)
    temporary.replace(target)
    return target


def _sniff(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    return None


def _delete_item_file(item_id: int, url: str) -> None:
    name = media_name(url)
    if not name.startswith(f"item-{item_id}."):
        return
    if FILENAME_RE.fullmatch(name) is None:
        return
    path = image_dir() / name
    if path.is_file():
        path.unlink()
