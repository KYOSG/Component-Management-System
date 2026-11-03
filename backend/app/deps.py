from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.security import read_session

PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}


def session_user(request: Request, db: Session) -> User | None:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name, "")
    session = read_session(token, settings.secret_key) if token else None
    if session is None:
        return None
    user_id, session_token = session
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.session_token:
        return None
    if not hmac.compare_digest(user.session_token, session_token):
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = session_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(status_code=403, detail="请先修改初始密码")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
