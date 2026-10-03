from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    purchase_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"),
        nullable=True,
    )
    product_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    supplier_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    position_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"),
        nullable=True,
    )
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"),
        nullable=True,
    )
    zip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class SelfOperatedBatch(Base):
    __tablename__ = "self_operated_batches"

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id"),
        primary_key=True,
    )
    template_version_id: Mapped[int] = mapped_column(
        ForeignKey("input_versions.id"),
    )
    rule_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("self_operated_overreceipt_rule_versions.id"),
        nullable=True,
    )
    inbound_original_name: Mapped[str] = mapped_column(String(255), default="")
    inbound_storage_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SelfOperatedSiteResolution(Base):
    __tablename__ = "self_operated_site_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "sku",
            "original_site",
            name="uq_self_operated_site_resolution",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    sku: Mapped[str] = mapped_column(String(200))
    original_site: Mapped[str] = mapped_column(String(100))
    full_site: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )


class BatchFile(Base):
    __tablename__ = "batch_files"
    __table_args__ = (
        UniqueConstraint("batch_id", "file_order", name="uq_batch_file_order"),
        UniqueConstraint("batch_id", "original_name", name="uq_batch_original_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(Text)
    file_order: Mapped[int] = mapped_column(Integer)
    supplier_name: Mapped[str] = mapped_column(String(200), default="")
    supplier_code: Mapped[str] = mapped_column(String(100), default="")
    document_note: Mapped[str] = mapped_column(String(255), default="")
    delivery_total: Mapped[int] = mapped_column(Integer, default=0)
    import_total: Mapped[int] = mapped_column(Integer, default=0)
    manual_total: Mapped[int] = mapped_column(Integer, default=0)
    import_rows: Mapped[list] = mapped_column(JSON, default=list)
    result_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExceptionRecord(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_file_id: Mapped[int] = mapped_column(ForeignKey("batch_files.id"), index=True)
    sku: Mapped[str] = mapped_column(String(200))
    original_site: Mapped[str] = mapped_column(String(100), default="")
    full_site: Mapped[str] = mapped_column(Text, default="")
    destination: Mapped[str] = mapped_column(String(255), default="")
    delivery_quantity: Mapped[int] = mapped_column(Integer)
    allocated_quantity: Mapped[int] = mapped_column(Integer)
    purchase_allocated_quantity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    overreceipt_allocated_quantity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    overreceipt_remaining_quantity: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    manual_quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255))
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SplitRecord(Base):
    __tablename__ = "splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    exception_id: Mapped[int] = mapped_column(ForeignKey("exceptions.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    destination: Mapped[str] = mapped_column(String(255), default="")
    site: Mapped[str] = mapped_column(Text, default="")
    supplier_code: Mapped[str] = mapped_column(String(100), default="")
    sku: Mapped[str] = mapped_column(String(200), default="")
    delivery_note: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
