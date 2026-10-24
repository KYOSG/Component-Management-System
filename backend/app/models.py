from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Box(Base):
    __tablename__ = "boxes"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_box_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list[Item]] = relationship(back_populates="box")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("user_id", "lcsc_code", name="uq_item_user_lcsc"),
        UniqueConstraint("box_id", "row", "col", name="uq_item_cell"),
    )

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
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    box_id: Mapped[int | None] = mapped_column(ForeignKey("boxes.id"), nullable=True)
    row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    col: Mapped[int | None] = mapped_column(Integer, nullable=True)
    datasheet_url: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    box: Mapped[Box | None] = relationship(back_populates="items")


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
