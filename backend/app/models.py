from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_session_token() -> str:
    return secrets.token_urlsafe(24)


class Base(DeclarativeBase):
    pass


class SystemConfig(Base):
    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    session_token: Mapped[str] = mapped_column(String(64), default=new_session_token)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpecCategory(Base):
    __tablename__ = "spec_categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_spec_category_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    lcsc_keywords: Mapped[str] = mapped_column(Text, default="[]")
    fields: Mapped[str] = mapped_column(Text, default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Box(Base):
    __tablename__ = "boxes"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_box_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    box_type: Mapped[str] = mapped_column(String(16), default="grid", server_default="grid")
    slot_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    locations: Mapped[list[ItemLocation]] = relationship(back_populates="box")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("user_id", "lcsc_code", name="uq_item_user_lcsc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lcsc_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mpn: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    brand: Mapped[str] = mapped_column(String(255), default="")
    footprint: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(255), default="")
    value: Mapped[str] = mapped_column(String(255), default="")
    params: Mapped[str] = mapped_column(Text, default="")
    specs: Mapped[str] = mapped_column(Text, default="{}")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    datasheet_url: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    lcsc_sync_status: Mapped[str] = mapped_column(String(16), default="idle", server_default="idle")
    lcsc_sync_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    lcsc_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    locations: Mapped[list[ItemLocation]] = relationship(back_populates="item", cascade="all, delete-orphan")
    events: Mapped[list[StockEvent]] = relationship(back_populates="item", cascade="all, delete-orphan")


class ItemLocation(Base):
    __tablename__ = "item_locations"
    __table_args__ = (UniqueConstraint("box_id", "row", "col", name="uq_location_cell"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    location_type: Mapped[str] = mapped_column(String(16))
    box_id: Mapped[int | None] = mapped_column(ForeignKey("boxes.id"), nullable=True)
    row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reel_label: Mapped[str] = mapped_column(String(64), default="")
    slot_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="locations")
    box: Mapped[Box | None] = relationship(back_populates="locations")


class StockEvent(Base):
    __tablename__ = "stock_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(16))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="events")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str] = mapped_column(String(255), default="")
    format: Mapped[str] = mapped_column(String(32))
    purchase_sets: Mapped[int] = mapped_column(Integer, default=1)
    order_no: Mapped[str] = mapped_column(String(128), default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list[ProjectLine]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectLine(Base):
    __tablename__ = "project_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, default=0)
    designators: Mapped[str] = mapped_column(Text, default="")
    quantity_per_board: Mapped[int] = mapped_column(Integer, default=0)
    quantity_required: Mapped[int] = mapped_column(Integer, default=0)
    lcsc_code: Mapped[str] = mapped_column(String(64), default="")
    mpn: Mapped[str] = mapped_column(String(255), default="")
    brand: Mapped[str] = mapped_column(String(255), default="")
    footprint: Mapped[str] = mapped_column(String(255), default="")
    value: Mapped[str] = mapped_column(String(255), default="")
    params: Mapped[str] = mapped_column(Text, default="")
    product_name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(255), default="")
    match_status: Mapped[str] = mapped_column(String(32), default="")
    matched_item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    suggestions_json: Mapped[str] = mapped_column(Text, default="")
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="lines")
