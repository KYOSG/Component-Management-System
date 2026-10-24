from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import Box, Item, Project, ProjectLine, User
from app.routers.auth import _check_password
from app.schemas import UserOut, UserWrite
from app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


def normalize_account(value: str) -> str:
    account = value.strip().lower()
    if not account or any(char.isspace() for char in account) or len(account) > 255:
        raise HTTPException(status_code=400, detail="请填写账号")
    return account


def _admin_count(db: Session, exclude_id: int | None = None) -> int:
    filters = [User.is_admin.is_(True)]
    if exclude_id is not None:
        filters.append(User.id != exclude_id)
    return db.scalar(select(func.count()).select_from(User).where(*filters)) or 0


def delete_user_data(db: Session, user: User) -> None:
    item_ids = list(db.scalars(select(Item.id).where(Item.user_id == user.id)).all())
    if item_ids:
        db.execute(update(ProjectLine).where(ProjectLine.matched_item_id.in_(item_ids)).values(matched_item_id=None))
    project_ids = list(db.scalars(select(Project.id).where(Project.user_id == user.id)).all())
    if project_ids:
        db.execute(delete(ProjectLine).where(ProjectLine.project_id.in_(project_ids)))
        db.execute(delete(Project).where(Project.id.in_(project_ids)))
    db.execute(delete(Item).where(Item.user_id == user.id))
    db.execute(delete(Box).where(Box.user_id == user.id))
    db.delete(user)


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.post("", response_model=UserOut)
def create_user(body: UserWrite, db: Session = Depends(get_db), _admin: User = Depends(require_admin)) -> User:
    account = normalize_account(body.email)
    if not body.password:
        raise HTTPException(status_code=400, detail="请填写密码")
    _check_password(body.password)
    if db.scalar(select(User.id).where(User.email == account)):
        raise HTTPException(status_code=400, detail="账号已存在")
    user = User(email=account, password_hash=hash_password(body.password), is_admin=body.is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserWrite,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    account = normalize_account(body.email)
    taken = db.scalar(select(User.id).where(User.email == account, User.id != user.id))
    if taken:
        raise HTTPException(status_code=400, detail="账号已存在")
    if user.is_admin and not body.is_admin and _admin_count(db, exclude_id=user.id) == 0:
        raise HTTPException(status_code=400, detail="至少保留一名管理员")
    if body.password:
        _check_password(body.password)
        user.password_hash = hash_password(body.password)
    user.email = account
    user.is_admin = body.is_admin
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def remove_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的账号")
    if user.is_admin and _admin_count(db, exclude_id=user.id) == 0:
        raise HTTPException(status_code=400, detail="至少保留一名管理员")
    delete_user_data(db, user)
    db.commit()
    return {"ok": True}
