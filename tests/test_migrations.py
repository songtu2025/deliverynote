from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect, text

from delivery_note.migrations.overreceipt_rules import migrate
from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Base,
    Batch,
    BatchOverreceiptRule,
    ExceptionRecord,
    OverreceiptRuleVersion,
    PositionDraftRow,
    PurchaseSyncJob,
)


POSITION_DRAFT_PAGE_INDEX = "ix_position_draft_rows_draft_id_deleted_row_order"


class SchemaMigrationRunnerTests(unittest.TestCase):
    def test_fresh_schema_is_complete_and_runner_is_idempotent(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'migration.db'}"

            migrate_schema(database_url)
            migrate_schema(database_url)

            database = Database(database_url)
            try:
                inspector = inspect(database.engine)
                tables = set(inspector.get_table_names())
                batch_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(Batch.__tablename__)
                }
                purchase_sync_columns = {
                    column["name"]: column
                    for column in inspector.get_columns(PurchaseSyncJob.__tablename__)
                }
                exception_columns = {
                    column["name"]
                    for column in inspector.get_columns(ExceptionRecord.__tablename__)
                }
            finally:
                database.dispose()

        self.assertIn(OverreceiptRuleVersion.__tablename__, tables)
        self.assertIn(BatchOverreceiptRule.__tablename__, tables)
        for column in (
            "purchase_version_id",
            "position_version_id",
            "template_version_id",
        ):
            self.assertTrue(batch_columns[column]["nullable"])
        for column in ("product_version_id", "supplier_version_id"):
            self.assertTrue(purchase_sync_columns[column]["nullable"])
        self.assertTrue(
            {
                "purchase_allocated_quantity",
                "overreceipt_allocated_quantity",
                "overreceipt_remaining_quantity",
            }.issubset(exception_columns)
        )

    def test_existing_exception_reasons_receive_stable_codes(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'migration.db'}"
            database = Database(database_url)
            try:
                database.create_schema()
                with database.engine.begin() as connection:
                    if "reason_code" in {
                        column["name"]
                        for column in inspect(database.engine).get_columns("exceptions")
                    }:
                        connection.execute(
                            text("ALTER TABLE exceptions DROP COLUMN reason_code")
                        )
                    connection.execute(
                        text(
                            "INSERT INTO exceptions "
                            "(batch_file_id, sku, original_site, full_site, "
                            "destination, delivery_quantity, allocated_quantity, "
                            "manual_quantity, reason, status, created_at) "
                            "VALUES (1, 'SKU-A', '', '', '', 1, 0, 1, "
                            "'产品信息站点不唯一', 'pending', CURRENT_TIMESTAMP), "
                            "(1, 'SKU-B', '', '', '', 1, 0, 1, "
                            "'历史未知原因', 'pending', CURRENT_TIMESTAMP)"
                        )
                    )
            finally:
                database.dispose()

            migrate_schema(database_url)
            migrate_schema(database_url)
            database = Database(database_url)
            try:
                with database.engine.connect() as connection:
                    rows = connection.execute(
                        text("SELECT reason, reason_code FROM exceptions ORDER BY id")
                    ).all()
            finally:
                database.dispose()

        self.assertEqual(rows[0], ("产品信息站点不唯一", "ambiguous_product_site"))
        self.assertEqual(rows[1], ("历史未知原因", "unknown"))


class PositionDraftRowIndexMigrationTests(unittest.TestCase):
    @staticmethod
    def indexes(database: Database) -> dict[str, dict]:
        return {
            index["name"]: index
            for index in inspect(database.engine).get_indexes(
                PositionDraftRow.__tablename__
            )
        }

    def test_fresh_metadata_schema_has_composite_page_index(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'fresh.db'}"
            database = Database(database_url)
            try:
                database.create_schema()
                indexes = self.indexes(database)
            finally:
                database.dispose()

        self.assertIn(POSITION_DRAFT_PAGE_INDEX, indexes)
        self.assertEqual(
            indexes[POSITION_DRAFT_PAGE_INDEX]["column_names"],
            ["draft_id", "deleted", "row_order"],
        )

    def test_runner_adds_missing_index_to_existing_table_idempotently(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'existing.db'}"
            database = Database(database_url)
            try:
                database.create_schema()
                if POSITION_DRAFT_PAGE_INDEX in self.indexes(database):
                    with database.engine.begin() as connection:
                        connection.execute(
                            text(f"DROP INDEX {POSITION_DRAFT_PAGE_INDEX}")
                        )
                self.assertNotIn(
                    POSITION_DRAFT_PAGE_INDEX,
                    self.indexes(database),
                )
            finally:
                database.dispose()

            migrate_schema(database_url)
            migrate_schema(database_url)

            database = Database(database_url)
            try:
                indexes = self.indexes(database)
            finally:
                database.dispose()

        self.assertIn(POSITION_DRAFT_PAGE_INDEX, indexes)

    def test_sqlite_page_plan_uses_composite_index_without_temp_sort(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'plan.db'}"
            migrate_schema(database_url)
            database = Database(database_url)
            try:
                with database.engine.connect() as connection:
                    plan = connection.execute(
                        text(
                            "EXPLAIN QUERY PLAN "
                            "SELECT * FROM position_draft_rows "
                            "WHERE draft_id = 1 AND deleted = 0 "
                            "ORDER BY row_order LIMIT 50"
                        )
                    ).all()
            finally:
                database.dispose()

        details = [str(row[-1]).upper() for row in plan]
        self.assertTrue(
            any(POSITION_DRAFT_PAGE_INDEX.upper() in detail for detail in details)
        )
        self.assertFalse(any("TEMP B-TREE" in detail for detail in details))


class OverreceiptMigrationTests(unittest.TestCase):
    def test_migration_adds_only_missing_tables_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'migration.db'}"
            database = Database(database_url)
            try:
                existing_tables = [
                    table
                    for table in Base.metadata.sorted_tables
                    if table
                    not in {
                        OverreceiptRuleVersion.__table__,
                        BatchOverreceiptRule.__table__,
                        ExceptionRecord.__table__,
                    }
                ]
                Base.metadata.create_all(database.engine, tables=existing_tables)
                with database.engine.begin() as connection:
                    connection.execute(
                        text(
                            """
                        CREATE TABLE exceptions (
                            id INTEGER PRIMARY KEY,
                            batch_file_id INTEGER NOT NULL,
                            sku VARCHAR(200) NOT NULL,
                            original_site VARCHAR(100) NOT NULL DEFAULT '',
                            full_site TEXT NOT NULL DEFAULT '',
                            destination VARCHAR(255) NOT NULL DEFAULT '',
                            delivery_quantity INTEGER NOT NULL,
                            allocated_quantity INTEGER NOT NULL,
                            manual_quantity INTEGER NOT NULL,
                            reason VARCHAR(255) NOT NULL,
                            status VARCHAR(20) NOT NULL DEFAULT 'pending',
                            created_at DATETIME NOT NULL
                        )
                        """
                        )
                    )
            finally:
                database.dispose()

            migrate(database_url)
            migrate(database_url)

            database = Database(database_url)
            try:
                tables = set(inspect(database.engine).get_table_names())
                exception_columns = {
                    column["name"]
                    for column in inspect(database.engine).get_columns(
                        ExceptionRecord.__tablename__
                    )
                }
            finally:
                database.dispose()
        self.assertIn("overreceipt_rule_versions", tables)
        self.assertIn("batch_overreceipt_rules", tables)
        self.assertIn("purchase_allocated_quantity", exception_columns)
        self.assertIn("overreceipt_allocated_quantity", exception_columns)
        self.assertIn("overreceipt_remaining_quantity", exception_columns)


if __name__ == "__main__":
    unittest.main()
