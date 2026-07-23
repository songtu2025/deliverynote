from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="operator")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("input_drafts.id"), index=True)
    row_order: Mapped[int] = mapped_column(Integer)
    base_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    store_site: Mapped[str] = mapped_column(Text, default="")
    jiaji_sku: Mapped[str] = mapped_column(Text, default="")
    msku: Mapped[str] = mapped_column(Text, default="")
    scale_position: Mapped[str] = mapped_column(Text, default="")
    stocking_position: Mapped[str] = mapped_column(Text, default="")
    ordered_days: Mapped[str] = mapped_column(Text, default="")
    change_type: Mapped[str] = mapped_column(String(20), default="unchanged")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    purchase_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    product_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    supplier_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    position_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    template_version_id: Mapped[int] = mapped_column(ForeignKey("input_versions.id"))
    zip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OverreceiptRuleVersion(Base):
    __tablename__ = "overreceipt_rule_versions"
    __table_args__ = (
        CheckConstraint("short_tail_limit >= 0", name="ck_overreceipt_short_limit"),
        CheckConstraint("medium_tail_limit >= 0", name="ck_overreceipt_medium_limit"),
        CheckConstraint("long_tail_limit >= 0", name="ck_overreceipt_long_limit"),
        Index(
            "uq_active_overreceipt_rule",
            "active",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    short_tail_limit: Mapped[int] = mapped_column(Integer)
    medium_tail_limit: Mapped[int] = mapped_column(Integer)
    long_tail_limit: Mapped[int] = mapped_column(Integer)
    allowed_warehouses: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BatchOverreceiptRule(Base):
    __tablename__ = "batch_overreceipt_rules"

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id"),
        primary_key=True,
    )
    rule_version_id: Mapped[int] = mapped_column(
        ForeignKey("overreceipt_rule_versions.id"),
        index=True,
    )


class BatchFile(Base):
    __tablename__ = "batch_files"
    __table_args__ = (
        UniqueConstraint("batch_id", "file_order", name="uq_batch_file_order"),
        UniqueConstraint(
            "batch_id", "original_name", name="uq_batch_original_name"
        ),
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


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("batch_id", "kind", name="uq_batch_job_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
