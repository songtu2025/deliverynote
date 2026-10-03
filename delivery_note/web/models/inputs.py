from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow

POSITION_DRAFT_PAGE_INDEX_NAME = "ix_position_draft_rows_draft_id_deleted_row_order"


class InputVersion(Base):
    __tablename__ = "input_versions"
    __table_args__ = (
        UniqueConstraint("kind", "name", name="uq_input_kind_name"),
        Index(
            "uq_active_input_kind",
            "kind",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(200))
    original_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class InputDraft(Base):
    __tablename__ = "input_drafts"
    __table_args__ = (
        Index(
            "uq_editing_input_draft_kind",
            "kind",
            unique=True,
            postgresql_where=text("status = 'editing'"),
            sqlite_where=text("status = 'editing'"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    base_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    status: Mapped[str] = mapped_column(String(20), default="editing", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {
        "version_id_col": revision,
        "version_id_generator": False,
    }
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )


class PositionDraftRow(Base):
    __tablename__ = "position_draft_rows"
    __table_args__ = (
        Index(
            POSITION_DRAFT_PAGE_INDEX_NAME,
            "draft_id",
            "deleted",
            "row_order",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("input_drafts.id"), index=True)
    row_order: Mapped[int] = mapped_column(Integer)
    base_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    store_site: Mapped[str] = mapped_column(Text, default="")
    jiaji_sku: Mapped[str] = mapped_column(Text, default="")
    msku: Mapped[str] = mapped_column(Text, default="")
    scale_position: Mapped[str] = mapped_column(Text, default="")
    stocking_position: Mapped[str] = mapped_column(Text, default="")
    _legacy_ordered_days: Mapped[str] = mapped_column(
        "ordered_days",
        Text,
        default="",
    )
    change_type: Mapped[str] = mapped_column(String(20), default="unchanged")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
