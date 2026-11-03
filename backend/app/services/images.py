from __future__ import annotations

import ipaddress
import logging
import re
import shutil
import socket
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import app.database as database
from app.database import sqlite_path
from app.models import Item

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
SUFFIXES = (".jpg", ".png", ".webp", ".gif")
FILENAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}\.(jpg|png|webp|gif)$")


class UnsafeUrl(Exception):
    pass


def safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", value or "")[:60]


def image_root(database_url: str | None = None) -> Path:
    chosen = database.current_url if database_url is None else database_url
    path = sqlite_path(chosen)
    if path is not None:
        return path.parent / "images" / (safe_stem(path.stem) or "default")
    try:
        name = make_url(chosen).database or ""
    except Exception:
        name = ""
    return Path("data") / "images" / (safe_stem(name) or "default")


def image_dir(user_id: int, database_url: str | None = None, *, create: bool = False) -> Path:
    folder = image_root(database_url) / f"u{int(user_id)}"
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def remove_user_images(user_id: int) -> None:
    folder = image_dir(user_id)
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def is_remote(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def is_local(url: str) -> bool:
    return url.startswith("/api/media/")


def media_name(url: str) -> str:
    return Path(url).name


def display_image_url(url: str, user_id: int) -> str:
    text = (url or "").strip()
    if not is_local(text):
        return ""
    name = media_name(text)
    if FILENAME_RE.fullmatch(name) is None:
        return ""
    if not (image_dir(user_id) / name).is_file():
        return ""
    return f"/api/media/{name}"


def stem_for(item_id: int, lcsc_code: str | None) -> str:
    code = safe_stem(lcsc_code or "")
    if code:
        return f"lcsc-{code}"
    return f"item-{item_id}"


def find_file(stem: str, user_id: int, database_url: str | None = None) -> Path | None:
    folder = image_dir(user_id, database_url)
    for ext in SUFFIXES:
        path = folder / f"{stem}{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def localize(url: str, stem: str, user_id: int, *, refresh: bool = False, database_url: str | None = None) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    if is_local(text):
        name = media_name(text)
        if FILENAME_RE.fullmatch(name) and (image_dir(user_id, database_url) / name).is_file():
            return f"/api/media/{name}"
        return ""
    if not is_remote(text):
        return ""
    existing = find_file(stem, user_id, database_url)
    if existing is not None and not refresh:
        return f"/api/media/{existing.name}"
    saved = _download(text, stem, user_id, database_url)
    if saved is not None:
        return f"/api/media/{saved.name}"
    if existing is not None:
        return f"/api/media/{existing.name}"
    return ""


def assign_image(item: Item, incoming: str) -> None:
    text = (incoming or "").strip()
    previous = item.image_url or ""
    stem = stem_for(item.id, item.lcsc_code)
    if not text:
        if is_remote(previous):
            local = localize(previous, stem, item.user_id)
            item.image_url = local or previous
            return
        _delete_item_file(item, previous)
        item.image_url = ""
        return
    if is_local(text) or is_remote(text):
        local = localize(text, stem, item.user_id, refresh=is_remote(text))
        if local:
            if previous.startswith(f"/api/media/item-{item.id}.") and previous != local:
                _delete_item_file(item, previous)
            item.image_url = local
            return
    item.image_url = display_image_url(previous, item.user_id)


def delete_item_image(item: Item) -> None:
    _delete_item_file(item, item.image_url or "")


def cache_remote_item_images(session_factory, database_url: str) -> None:
    db: Session = session_factory()
    try:
        items = db.scalars(select(Item).where(Item.image_url.like("http%"))).all()
        changed = False
        for item in items:
            url = item.image_url or ""
            if not is_remote(url):
                continue
            local = localize(url, stem_for(item.id, item.lcsc_code), item.user_id, database_url=database_url)
            if local:
                item.image_url = local
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def resolve_host(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def _public_address(text: str) -> bool:
    address = ipaddress.ip_address(text.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def check_public_url(url: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrl("只允许 http/https 图片地址")
    host = parsed.host
    if not host:
        raise UnsafeUrl("图片地址缺少主机名")
    try:
        addresses = resolve_host(host)
    except OSError as exc:
        raise UnsafeUrl(f"无法解析图片主机：{host}") from exc
    if not addresses:
        raise UnsafeUrl(f"无法解析图片主机：{host}")
    for address in addresses:
        try:
            public = _public_address(address)
        except ValueError:
            public = False
        if not public:
            raise UnsafeUrl(f"不允许从内网或本机地址下载图片：{host}")


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"})


def fetch_image_bytes(url: str) -> tuple[bytes, str]:
    current = url
    with _client() as client:
        for _hop in range(MAX_REDIRECTS + 1):
            check_public_url(current)
            with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        raise UnsafeUrl("图片地址跳转缺少目标")
                    current = str(response.url.join(location))
                    continue
                response.raise_for_status()
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > MAX_BYTES:
                    raise UnsafeUrl("图片超过 5MB")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise UnsafeUrl("图片超过 5MB")
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "")
    raise UnsafeUrl("图片地址跳转次数过多")


def _download(url: str, stem: str, user_id: int, database_url: str | None) -> Path | None:
    try:
        content, content_type = fetch_image_bytes(url)
    except UnsafeUrl as exc:
        logger.warning("拒绝下载物料图片：%s", exc)
        return None
    except Exception as exc:
        logger.warning("物料图片下载失败：%s", exc)
        return None
    if not content:
        logger.warning("物料图片为空")
        return None
    ext = EXTENSIONS.get(content_type.split(";", 1)[0].strip().lower()) or _sniff(content)
    if ext is None:
        logger.warning("物料图片格式无法识别")
        return None
    folder = image_dir(user_id, database_url, create=True)
    for old in folder.glob(f"{stem}.*"):
        if old.suffix.lower() in SUFFIXES and old.suffix.lower() != ext:
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


def _delete_item_file(item: Item, url: str) -> None:
    name = media_name(url)
    if not name.startswith(f"item-{item.id}."):
        return
    if FILENAME_RE.fullmatch(name) is None:
        return
    path = image_dir(item.user_id) / name
    if path.is_file():
        path.unlink()
