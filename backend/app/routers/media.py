from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.deps import get_current_user
from app.models import User
from app.services.images import FILENAME_RE, image_dir

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{filename}")
def read_image(filename: str, user: User = Depends(get_current_user)) -> FileResponse:
    if FILENAME_RE.fullmatch(filename) is None:
        raise HTTPException(status_code=404, detail="图片不存在")
    path = image_dir(user.id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
