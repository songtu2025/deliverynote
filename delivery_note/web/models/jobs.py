from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


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


class PurchaseSyncJob(Base):
    __tablename__ = "purchase_sync_jobs"
    __table_args__ = (
        UniqueConstraint("active_slot", name="uq_active_purchase_sync_job"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    base_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"), nullable=True
    )
    product_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"), nullable=True
    )
    supplier_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"), nullable=True
    )
    candidate_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"), nullable=True
    )
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    processed_orders: Mapped[int] = mapped_column(Integer, default=0)
    raw_detail_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_detail_count: Mapped[int] = mapped_column(Integer, default=0)
    filtered_detail_count: Mapped[int] = mapped_column(Integer, default=0)
    current_order: Mapped[str | None] = mapped_column(Text, nullable=True)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SelfOperatedInboundSyncJob(Base):
    __tablename__ = "self_operated_inbound_sync_jobs"
    __table_args__ = (
        UniqueConstraint(
            "active_slot",
            name="uq_active_self_operated_inbound_sync_job",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    base_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"), nullable=True
    )
    candidate_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("input_versions.id"), nullable=True
    )
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    raw_detail_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_detail_count: Mapped[int] = mapped_column(Integer, default=0)
    filtered_detail_count: Mapped[int] = mapped_column(Integer, default=0)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
