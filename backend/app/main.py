from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.bootstrap import prepare_database
from app.config import get_settings
from app.routers import auth, boxes, items, lcsc, projects, settings, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    prepare_database()
    yield


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


app = FastAPI(title="物品映射", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(lcsc.router)
app.include_router(items.router)
app.include_router(boxes.router)
app.include_router(projects.router)
app.include_router(users.router)
app.include_router(settings.router)

static_dir = get_settings().static_dir
if static_dir and (Path(static_dir) / "index.html").is_file():
    app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="spa")
