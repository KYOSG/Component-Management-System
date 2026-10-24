from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import AuthIn, UserOut
from app.security import hash_password, sign_session, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_password(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码过长")


def _set_session(response: Response, user_id: int) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        sign_session(user_id, settings.secret_key, settings.session_ttl),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl,
        path="/",
    )


@router.post("/register", response_model=UserOut)
def register(body: AuthIn, response: Response, db: Session = Depends(get_db)) -> User:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    _check_password(body.password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=400, detail="邮箱已注册")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_session(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(body: AuthIn, response: Response, db: Session = Depends(get_db)) -> User:
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="邮箱或密码错误")
    _set_session(response, user.id)
    return user


@router.post("/logout")
def logout(response: Response) -> dict:
    settings = get_settings()
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
