#!/usr/bin/env python3
"""把电子元件库打成可在 Linux 的 Python 环境中运行的目录。

在仓库根目录执行:

    python scripts/pack.py

产物:

    release/电子元件库/          Linux 上执行 python3 run.py
    release/电子元件库.zip
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def repository_root() -> Path:
    for candidate in (HERE, HERE.parent):
        if (candidate / "backend" / "app" / "main.py").is_file():
            return candidate
    return HERE


ROOT = repository_root()
FRONTEND = ROOT / "frontend"
RELEASE = ROOT / "release"
PACKAGE_NAME = "电子元件库"
PACKAGE = RELEASE / PACKAGE_NAME
SKIP_ZIP_PARTS = {".venv", "data", "__pycache__", "secret_key"}
TEXT_SUFFIXES = {".py", ".txt", ".md"}

README = """电子元件库

在 Linux 上运行。需要 Python 3.10 或更高版本，不需要 Node.js。

已经激活虚拟环境或 conda 时，直接使用这个环境：

    python3 run.py

缺少依赖时会安装进当前环境。没有激活环境时，同样执行 python3 run.py，
这时会在当前目录创建 .venv 并安装依赖，需要联网。
Debian/Ubuntu 如果创建虚拟环境失败，先执行: sudo apt install python3-venv

有图形界面时会打开 http://127.0.0.1:8000。没有图形界面时，用这个地址自行访问。
按 Ctrl+C 停止。

首次登录的管理员账号是 admin，密码是 admin。登录后必须先修改密码。

数据、图片和登录密钥都在本目录的 data 文件夹。备份时复制整个 data。
重新解压时不要覆盖或删除 data。

可选参数：

    python3 run.py --port 9000
    python3 run.py --host 0.0.0.0
    python3 run.py --no-browser
    python3 run.py --browser

--host 0.0.0.0 允许同一局域网里的其他设备访问。

依赖安装较慢时，可以先指定镜像：

    export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
    python3 run.py
"""


def say(message: str) -> None:
    print(message, flush=True)


def require_python() -> None:
    if sys.version_info >= (3, 10):
        return
    current = ".".join(str(part) for part in sys.version_info[:3])
    raise SystemExit(f"需要 Python 3.10 或更高版本，当前是 {current}")


def tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit("未找到 Node.js。打包需要先安装 Node.js 来构建页面，安装后重新执行 python scripts/pack.py。")


def run_command(command: list[str], cwd: Path) -> None:
    display = " ".join(command)
    if os.name == "nt":
        command = ["cmd", "/c", *command]
    try:
        subprocess.check_call(command, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"命令失败，退出码 {exc.returncode}：{display}") from None


def build_frontend() -> None:
    if not (FRONTEND / "package.json").is_file():
        raise SystemExit("找不到 frontend/package.json。")
    node = tool("node")
    npm = tool("npm")
    say(f"Node: {node}")
    if not (FRONTEND / "node_modules").is_dir():
        say("正在安装前端依赖……")
        if (FRONTEND / "package-lock.json").is_file():
            run_command([npm, "ci"], FRONTEND)
        else:
            run_command([npm, "install"], FRONTEND)
    say("正在构建前端页面……")
    run_command([npm, "run", "build"], FRONTEND)
    if not (FRONTEND / "dist" / "index.html").is_file():
        raise SystemExit("前端构建结束，但没有生成 frontend/dist/index.html。")


def replace_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))


def write_lf(src: Path, dst: Path) -> None:
    dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))


def assemble() -> None:
    if not (ROOT / "backend" / "app" / "main.py").is_file():
        raise SystemExit("找不到 backend/app，请在仓库根目录运行 python scripts/pack.py。")
    if not (HERE / "run.py").is_file():
        raise SystemExit("找不到 scripts/run.py。")
    if not (FRONTEND / "dist" / "index.html").is_file():
        raise SystemExit("找不到 frontend/dist/index.html。")
    try:
        PACKAGE.mkdir(parents=True, exist_ok=True)
        say("正在组装打包目录……")
        replace_tree(ROOT / "backend" / "app", PACKAGE / "app")
        replace_tree(FRONTEND / "dist", PACKAGE / "static")
        write_lf(ROOT / "backend" / "requirements.txt", PACKAGE / "requirements.txt")
        write_lf(HERE / "run.py", PACKAGE / "run.py")
        (PACKAGE / "使用说明.txt").write_bytes(README.replace("\r\n", "\n").encode("utf-8"))
        for name in ("start.sh", "start.bat"):
            legacy = PACKAGE / name
            if legacy.exists():
                legacy.unlink()
        stale_venv = PACKAGE / ".venv"
        if stale_venv.exists():
            shutil.rmtree(stale_venv)
    except OSError as exc:
        raise SystemExit(f"无法写入 {PACKAGE}：{exc}\n请先关闭正在运行的程序后重试。") from None


def write_zip() -> Path:
    dest = RELEASE / f"{PACKAGE_NAME}.zip"
    say("正在压缩……")
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in PACKAGE.rglob("*"):
            relative = path.relative_to(PACKAGE)
            if any(part in SKIP_ZIP_PARTS for part in relative.parts):
                continue
            if not path.is_file() or path.suffix == ".pyc":
                continue
            data = path.read_bytes()
            if path.suffix in TEXT_SUFFIXES or path.name == "requirements.txt":
                data = data.replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo(Path(PACKAGE_NAME).joinpath(relative).as_posix())
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.date_time = time.localtime(path.stat().st_mtime)[:6]
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    return dest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打包电子元件库，供 Linux 上的 Python 环境运行")
    parser.add_argument("--skip-build", action="store_true", help="不重新构建前端，直接使用已有的 frontend/dist")
    parser.add_argument("--no-zip", action="store_true", help="只生成目录，不压缩 zip")
    return parser.parse_args()


def main() -> None:
    os.chdir(ROOT)
    require_python()
    args = parse_args()
    if args.skip_build:
        if not (FRONTEND / "dist" / "index.html").is_file():
            raise SystemExit("指定了 --skip-build，但 frontend/dist/index.html 不存在。")
    else:
        build_frontend()
    assemble()
    zip_path = None if args.no_zip else write_zip()
    say("")
    say("打包完成，请在 Linux 上运行。")
    say(f"目录: {PACKAGE}")
    if zip_path is not None:
        say(f"压缩包: {zip_path}")
    say("在 Linux 上执行 python3 run.py。")


if __name__ == "__main__":
    main()
