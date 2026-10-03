"""保护模型注册、数据库约束和默认值的公开契约。"""

import json
import subprocess
import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    ColumnDefault,
    DateTime,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.dialects import postgresql, sqlite

from delivery_note.web import models

MODEL_TABLES = {
    "User": "users",
    "AuthSession": "auth_sessions",
    "AuditLog": "audit_logs",
    "InputVersion": "input_versions",
    "InputDraft": "input_drafts",
    "PositionDraftRow": "position_draft_rows",
    "Batch": "batches",
    "SelfOperatedBatch": "self_operated_batches",
    "SelfOperatedSiteResolution": "self_operated_site_resolutions",
    "BatchFile": "batch_files",
    "ExceptionRecord": "exceptions",
    "SplitRecord": "splits",
    "OverreceiptRuleVersion": "overreceipt_rule_versions",
    "SelfOperatedOverreceiptRuleVersion": "self_operated_overreceipt_rule_versions",
    "BatchOverreceiptRule": "batch_overreceipt_rules",
    "Job": "jobs",
    "PurchaseSyncJob": "purchase_sync_jobs",
    "SelfOperatedInboundSyncJob": "self_operated_inbound_sync_jobs",
}


class ModelContractTests(unittest.TestCase):
    def test_package_exports_the_original_model_objects(self) -> None:
        groups = {
            "accounts": ("User", "AuthSession", "AuditLog"),
            "inputs": ("InputVersion", "InputDraft", "PositionDraftRow"),
            "batches": (
                "Batch",
                "SelfOperatedBatch",
                "SelfOperatedSiteResolution",
                "BatchFile",
                "ExceptionRecord",
                "SplitRecord",
            ),
            "rules": (
                "OverreceiptRuleVersion",
                "SelfOperatedOverreceiptRuleVersion",
                "BatchOverreceiptRule",
            ),
            "jobs": ("Job", "PurchaseSyncJob", "SelfOperatedInboundSyncJob"),
            "base": ("Base", "utcnow"),
        }
        for group, names in groups.items():
            provider = import_module(f"delivery_note.web.models.{group}")
            for name in names:
                with self.subTest(group=group, symbol=name):
                    self.assertIs(getattr(models, name), getattr(provider, name))
        self.assertEqual(
            set(models.__all__),
            set(MODEL_TABLES) | {"Base", "utcnow", "POSITION_DRAFT_PAGE_INDEX_NAME"},
        )
        inputs = import_module("delivery_note.web.models.inputs")
        self.assertEqual(
            models.POSITION_DRAFT_PAGE_INDEX_NAME, inputs.POSITION_DRAFT_PAGE_INDEX_NAME
        )

    def assert_fresh_registration(self, setup: str, expression: str) -> None:
        # 独立进程避免其他测试提前导入 API，掩盖模型注册遗漏。
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import json\n{setup}\nprint(json.dumps({expression}))",
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), sorted(MODEL_TABLES.values()))

    def test_base_import_alone_registers_all_tables(self) -> None:
        self.assert_fresh_registration(
            "from delivery_note.web.models import Base",
            "sorted(Base.metadata.tables)",
        )

    def test_base_module_import_alone_registers_all_tables(self) -> None:
        self.assert_fresh_registration(
            "from delivery_note.web.models.base import Base",
            "sorted(Base.metadata.tables)",
        )

    def test_database_import_alone_creates_all_tables(self) -> None:
        self.assert_fresh_registration(
            "from delivery_note.web.database import Database\n"
            "from sqlalchemy import inspect\n"
            "database = Database('sqlite+pysqlite:///:memory:')\n"
            "database.create_schema()",
            "sorted(inspect(database.engine).get_table_names())",
        )

    def test_public_models_share_one_registry(self) -> None:
        self.assertEqual(set(models.Base.metadata.tables), set(MODEL_TABLES.values()))
        self.assertEqual(
            {mapper.class_ for mapper in models.Base.registry.mappers},
            {getattr(models, name) for name in MODEL_TABLES},
        )
        for name, table_name in MODEL_TABLES.items():
            with self.subTest(model=name):
                model = getattr(models, name)
                self.assertIs(model.metadata, models.Base.metadata)
                self.assertIs(model.registry, models.Base.registry)
                self.assertIs(model.__table__, models.Base.metadata.tables[table_name])
                for foreign_key in model.__table__.foreign_keys:
                    self.assertIs(
                        foreign_key.column.table.metadata, models.Base.metadata
                    )

    def test_draft_revision_controls_optimistic_locking(self) -> None:
        mapper = inspect(models.InputDraft)
        self.assertIs(mapper.version_id_col, models.InputDraft.__table__.c.revision)
        self.assertIs(mapper.version_id_generator, False)
        default = models.Base.metadata.tables["input_drafts"].c.revision.default
        assert isinstance(default, ColumnDefault)
        self.assertEqual(default.arg, 1)

    def test_datetime_defaults_preserve_naive_utc(self) -> None:
        self.assertIsNone(models.utcnow().tzinfo)
        for table in models.Base.metadata.tables.values():
            for column in table.columns:
                if isinstance(column.type, DateTime) and isinstance(
                    column.default, ColumnDefault
                ):
                    with self.subTest(table=table.name, column=column.name):
                        self.assertIs(column.default.arg.__wrapped__, models.utcnow)
                if isinstance(column.onupdate, ColumnDefault):
                    self.assertIs(column.onupdate.arg.__wrapped__, models.utcnow)

    def test_partial_unique_indexes_keep_both_dialects(self) -> None:
        expected = (
            (models.InputVersion, "uq_active_input_kind", "active", "active = 1"),
            (
                models.InputDraft,
                "uq_editing_input_draft_kind",
                "status = 'editing'",
                "status = 'editing'",
            ),
            (
                models.OverreceiptRuleVersion,
                "uq_active_overreceipt_rule",
                "active",
                "active = 1",
            ),
            (
                models.SelfOperatedOverreceiptRuleVersion,
                "uq_active_self_operated_overreceipt_rule",
                "active",
                "active = 1",
            ),
        )
        for model, name, pg_where, sqlite_where in expected:
            with self.subTest(index=name):
                index = next(
                    item
                    for item in models.Base.metadata.tables[model.__tablename__].indexes
                    if item.name == name
                )
                self.assertTrue(index.unique)
                for dialect, predicate in (
                    (postgresql.dialect(), pg_where),
                    (sqlite.dialect(), sqlite_where),
                ):
                    actual = index.dialect_options[dialect.name]["where"]
                    self.assertEqual(str(actual.compile(dialect=dialect)), predicate)

    def test_business_constraints_remain_named(self) -> None:
        expected = {
            "uq_input_kind_name",
            "uq_self_operated_site_resolution",
            "uq_batch_file_order",
            "uq_batch_original_name",
            "uq_batch_job_kind",
            "uq_active_purchase_sync_job",
            "uq_active_self_operated_inbound_sync_job",
            "ck_self_operated_allowance",
            "ck_overreceipt_short_limit",
            "ck_overreceipt_medium_limit",
            "ck_overreceipt_long_limit",
        }
        actual = {
            constraint.name
            for table in models.Base.metadata.tables.values()
            for constraint in table.constraints
            if isinstance(constraint, (UniqueConstraint, CheckConstraint))
            and constraint.name is not None
        }
        self.assertEqual(actual, expected)

    def test_position_legacy_column_and_page_index_remain(self) -> None:
        mapper = inspect(models.PositionDraftRow)
        table = models.Base.metadata.tables["position_draft_rows"]
        self.assertIs(
            mapper.attrs._legacy_ordered_days.columns[0], table.c.ordered_days
        )
        index = next(
            item
            for item in table.indexes
            if item.name == models.POSITION_DRAFT_PAGE_INDEX_NAME
        )
        self.assertEqual(
            [column.name for column in index.columns],
            ["draft_id", "deleted", "row_order"],
        )
