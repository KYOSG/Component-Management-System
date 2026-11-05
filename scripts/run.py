#!/usr/bin/env python3
"""在 Linux 的 Python 环境里启动电子元件库。

已激活虚拟环境或 conda 时，使用当前解释器：

    python3 scripts/run.py

打包目录里：

    python3 run.py
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PORT = 8000
RUNTIME_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "bcrypt",
    "httpx",
    "openpyxl",
    "xlrd",
    "pydantic",
    "multipart",
)


def project_root() -> Path:
    if (HERE / "backend" / "app" / "main.py").is_file() or (HERE / "app" / "main.py").is_file():
        return HERE
    if (HERE.parent / "backend" / "app" / "main.py").is_file():
        return HERE.parent
    return HERE


ROOT = project_root()


@dataclass(frozen=True)
class Layout:
    kind: str
    app_dir: Path
    static_dir: Path
    requirements: Path
    venv: Path


def say(message: str) -> None:
    print(message, flush=True)


def same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    except OSError:
        return False


def require_python() -> None:
    if sys.version_info >= (3, 10):
        return
    current = ".".join(str(part) for part in sys.version_info[:3])
    raise SystemExit(f"需要 Python 3.10 或更高版本，当前是 {current}")


def detect_layout() -> Layout:
    if (ROOT / "backend" / "app" / "main.py").is_file():
        return Layout(
            kind="source",
            app_dir=ROOT / "backend",
            static_dir=ROOT / "frontend" / "dist",
            requirements=ROOT / "backend" / "requirements.txt",
            venv=ROOT / "backend" / ".venv",
        )
    if (ROOT / "app" / "main.py").is_file():
        return Layout(
            kind="package",
            app_dir=ROOT,
            static_dir=ROOT / "static",
            requirements=ROOT / "requirements.txt",
            venv=ROOT / ".venv",
        )
    raise SystemExit("请在仓库根目录或打包后的目录里运行本脚本。")


def ensure_files(layout: Layout) -> None:
    if not layout.requirements.is_file():
        raise SystemExit(f"找不到依赖清单：{layout.requirements}")
    if (layout.static_dir / "index.html").is_file():
        return
    if layout.kind == "source":
        raise SystemExit(
            "还没有前端页面。请先在仓库根目录执行:\n"
            "    python scripts/pack.py\n"
        )
    raise SystemExit("打包目录缺少 static/index.html，请重新执行 python scripts/pack.py。")


def in_prepared_env() -> bool:
    if os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_PREFIX"):
        return True
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def dependencies_installed() -> bool:
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(name) is not None for name in RUNTIME_MODULES)


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def python_works(py: Path) -> bool:
    if not py.is_file():
        return False
    try:
        result = subprocess.run([str(py), "-c", "import sys"], capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


def requirements_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pip_install(py: Path, requirements: Path) -> None:
    say("正在安装依赖，需要联网，可能要几分钟。")
    try:
        subprocess.check_call(
            [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)]
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"依赖安装失败，退出码 {exc.returncode}。") from None


def prepare_venv(layout: Layout) -> Path:
    py = venv_python(layout.venv)
    stamp = layout.venv / ".requirements.sha256"
    digest = requirements_digest(layout.requirements)
    if not python_works(py):
        if layout.venv.exists():
            shutil.rmtree(layout.venv)
        say("当前没有已激活的 Python 环境，正在创建 .venv ……")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(layout.venv)])
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"创建虚拟环境失败，退出码 {exc.returncode}。\n"
                "Debian/Ubuntu 请先执行: sudo apt install python3-venv"
            ) from None
        py = venv_python(layout.venv)
        if not python_works(py):
            raise SystemExit("虚拟环境已创建，但其中的 Python 无法运行。")
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == digest and python_works(py):
        return py
    pip_install(py, layout.requirements)
    stamp.write_text(digest + "\n", encoding="utf-8")
    return py


def relaunch(py: Path) -> None:
    if same_path(Path(sys.executable), py):
        return
    if os.environ.get("CMS_RELAUNCHED") == "1":
        raise SystemExit("无法进入 .venv。请删除该目录后重试。")
    script = str(Path(__file__).resolve())
    argv = [str(py), script, *sys.argv[1:]]
    env = os.environ.copy()
    env["CMS_RELAUNCHED"] = "1"
    env["PYTHONUTF8"] = "1"
    if os.name == "posix":
        os.execve(str(py), argv, env)
    try:
        code = subprocess.call(argv, env=env)
    except KeyboardInterrupt:
        code = 0
    raise SystemExit(code)


def ensure_runtime(layout: Layout) -> None:
    if dependencies_installed():
        return
    if in_prepared_env():
        say(f"使用当前 Python 环境: {sys.executable}")
        pip_install(Path(sys.executable), layout.requirements)
        if dependencies_installed():
            return
        raise SystemExit("依赖安装后仍无法导入。请检查当前 Python 环境。")
    py = prepare_venv(layout)
    relaunch(py)


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def choose_port(host: str, requested: int | None) -> int:
    if requested is not None:
        if port_free(host, requested):
            return requested
        raise SystemExit(f"端口 {requested} 已被占用。")
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 20):
        if port_free(host, port):
            return port
    raise SystemExit(f"端口 {DEFAULT_PORT} 到 {DEFAULT_PORT + 19} 都被占用。")


def desktop_available() -> bool:
    if os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_when_ready(url: str) -> None:
    def worker() -> None:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status < 500:
                        webbrowser.open(url)
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)

    threading.Thread(target=worker, daemon=True).start()


def serve(layout: Layout, host: str, port: int, browser: bool) -> None:
    os.environ["STATIC_DIR"] = str(layout.static_dir.resolve())
    os.chdir(layout.app_dir)
    app_dir = str(layout.app_dir)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("依赖未安装完整。") from None

    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{port}"
    database = layout.app_dir / "data" / "app.db"
    say("")
    say(f"Python: {sys.executable}")
    say(f"地址: {url}")
    say(f"数据目录: {layout.app_dir / 'data'}")
    if not database.is_file():
        say("首次启动的管理员账号是 admin，密码是 admin。登录后需要先修改密码。")
    say("按 Ctrl+C 停止。")
    say("")
    if browser:
        open_when_ready(url)
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在 Linux 的 Python 环境中启动电子元件库")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认只允许本机访问")
    parser.add_argument("--port", type=int, default=None, help=f"端口，默认 {DEFAULT_PORT}，被占用时自动往后试")
    parser.add_argument("--browser", action="store_true", help="即使没有图形界面也尝试打开浏览器")
    parser.add_argument("--no-browser", action="store_true", help="启动后不打开浏览器")
    return parser.parse_args()


def main() -> None:
    require_python()
    args = parse_args()
    if args.port is not None and not (1 <= args.port <= 65535):
        raise SystemExit("端口必须在 1 到 65535 之间。")
    layout = detect_layout()
    ensure_files(layout)
    ensure_runtime(layout)
    port = choose_port(args.host, args.port)
    if args.port is None and port != DEFAULT_PORT:
        say(f"{DEFAULT_PORT} 已被占用，改用 {port}。")
    browser = args.browser or (desktop_available() and not args.no_browser)
    try:
        serve(layout, args.host, port, browser)
    except KeyboardInterrupt:
        say("\n已停止。")


if __name__ == "__main__":
    main()
