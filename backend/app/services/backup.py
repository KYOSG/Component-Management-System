from __future__ import annotations

import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from app.database import sqlite_path
from app.services.images import image_root


class BackupError(Exception):
    pass


def build_backup(database_url: str, out_path: str | os.PathLike) -> None:
    """把当前 SQLite 数据库和它的图片目录打成一个 zip。

    数据库用 sqlite3 的在线备份接口复制，备份过程中仍可正常读写。
    secret_key 不放进备份，恢复后旧的登录状态会失效，需要重新登录。
    """
    source = sqlite_path(database_url)
    if source is None or not source.is_file():
        raise BackupError("找不到当前数据库文件，无法备份")
    handle, raw = tempfile.mkstemp(suffix=".db", prefix="cms-db-")
    os.close(handle)
    snapshot = Path(raw)
    try:
        _copy_sqlite(source, snapshot)
        images = image_root(database_url)
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, f"database/{source.name}")
            if images.is_dir():
                for path in sorted(images.rglob("*")):
                    if path.is_file() and not path.name.endswith(".tmp"):
                        archive.write(path, f"images/{images.name}/{path.relative_to(images).as_posix()}")
    finally:
        snapshot.unlink(missing_ok=True)


def _copy_sqlite(source: Path, target: Path) -> None:
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
