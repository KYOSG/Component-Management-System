from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User, new_session_token
from app.ratelimit import login_limiter
from app.schemas import AuthIn, AuthOptionsOut, PasswordChangeIn, UserOut
from app.security import hash_password, sign_session, verify_password
from app.services.spec_config import seed_defaults
from app.services.system_config import registration_open

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_password(password: str) -> None:
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="密码过长")


def set_session(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        sign_session(user.id, user.session_token, settings.secret_key, settings.session_ttl),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(get_settings().cookie_name, path="/")


def rotate_session(user: User) -> None:
    user.session_token = new_session_token()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/options", response_model=AuthOptionsOut)
def options(db: Session = Depends(get_db)) -> AuthOptionsOut:
    return AuthOptionsOut(allow_register=registration_open(db))


@router.post("/register", response_model=UserOut)
def register(body: AuthIn, response: Response, db: Session = Depends(get_db)) -> User:
    if not registration_open(db):
        raise HTTPException(status_code=403, detail="管理员未开放注册")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    _check_password(body.password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=400, detail="邮箱已注册")
    user = User(email=email, password_hash=hash_password(body.password), session_token=new_session_token())
    db.add(user)
    db.flush()
    seed_defaults(db, user.id)
    db.commit()
    db.refresh(user)
    set_session(response, user)
    return user


@router.post("/login", response_model=UserOut)
def login(body: AuthIn, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    email = body.email.strip().lower()
    ip = _client_ip(request)
    if login_limiter.blocked(ip, email):
        raise HTTPException(status_code=429, detail="登录失败次数过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        login_limiter.fail(ip, email)
        raise HTTPException(status_code=400, detail="账号或密码错误")
    login_limiter.succeed(ip, email)
    if not user.session_token:
        rotate_session(user)
        db.commit()
    set_session(response, user)
    return user


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_session(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/password", response_model=UserOut)
def change_password(
    body: PasswordChangeIn,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    _check_password(body.new_password)
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="新密码不能和原密码相同")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    rotate_session(user)
    db.commit()
    db.refresh(user)
    set_session(response, user)
    return user
