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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow


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


class SelfOperatedOverreceiptRuleVersion(Base):
    __tablename__ = "self_operated_overreceipt_rule_versions"
    __table_args__ = (
        CheckConstraint("allowance >= 0", name="ck_self_operated_allowance"),
        Index(
            "uq_active_self_operated_overreceipt_rule",
            "active",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    allowance: Mapped[int] = mapped_column(Integer)
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
