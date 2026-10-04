from sqlalchemy import inspect, text

from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    OverreceiptRuleVersion,
    PurchaseSyncJob,
)
from tests.support.postgres import PostgreSQLCase


class MigrationTests(PostgreSQLCase):
    def test_unified_migration_creates_fresh_schema_idempotently(self):
        migrate_schema(self.database_url)
        migrate_schema(self.database_url)

        database = Database(self.database_url)
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
        self.assertTrue(batch_columns["purchase_version_id"]["nullable"])
        self.assertTrue(batch_columns["position_version_id"]["nullable"])
        self.assertTrue(batch_columns["template_version_id"]["nullable"])
        self.assertTrue(purchase_sync_columns["product_version_id"]["nullable"])
        self.assertTrue(purchase_sync_columns["supplier_version_id"]["nullable"])
        self.assertIn("purchase_allocated_quantity", exception_columns)
        self.assertIn("overreceipt_allocated_quantity", exception_columns)
        self.assertIn("overreceipt_remaining_quantity", exception_columns)

    def test_unified_migration_upgrades_legacy_schema_and_preserves_data(self):
        migrate_schema(self.database_url)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                user, batch, versions = self.create_batch(
                    session, "legacy-batch", "legacy", "-legacy"
                )
                sync_job = PurchaseSyncJob(
                    status="succeeded",
                    created_by=user.id,
                    product_version_id=versions["product"],
                    supplier_version_id=versions["supplier"],
                )
                session.add_all([batch, sync_job])
                session.flush()
                source = BatchFile(
                    batch_id=batch.id,
                    original_name="legacy.xlsx",
                    storage_path="/legacy.xlsx",
                    file_order=1,
                )
                session.add(source)
                session.flush()
                exception = ExceptionRecord(
                    batch_file_id=source.id,
                    sku="SKU-A",
                    delivery_quantity=1,
                    allocated_quantity=0,
                    manual_quantity=1,
                    reason="产品信息站点不唯一",
                )
                session.add(exception)
                session.commit()
                batch_id = batch.id
                sync_job_id = sync_job.id
                exception_id = exception.id

            with database.engine.begin() as connection:
                connection.execute(text("DROP TABLE batch_overreceipt_rules"))
                connection.execute(text("DROP TABLE overreceipt_rule_versions"))
                for column in (
                    "purchase_allocated_quantity",
                    "overreceipt_allocated_quantity",
                    "overreceipt_remaining_quantity",
                    "reason_code",
                ):
                    connection.execute(
                        text(f"ALTER TABLE exceptions DROP COLUMN {column}")
                    )
                for column in (
                    "purchase_version_id",
                    "position_version_id",
                    "template_version_id",
                ):
                    connection.execute(
                        text(f"ALTER TABLE batches ALTER COLUMN {column} SET NOT NULL")
                    )
                for column in ("product_version_id", "supplier_version_id"):
                    connection.execute(
                        text(
                            "ALTER TABLE purchase_sync_jobs "
                            f"ALTER COLUMN {column} SET NOT NULL"
                        )
                    )
        finally:
            database.dispose()

        migrate_schema(self.database_url)

        database = Database(self.database_url)
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
            with database.session() as session:
                batch = session.get(Batch, batch_id)
                sync_job = session.get(PurchaseSyncJob, sync_job_id)
                exception = session.get(ExceptionRecord, exception_id)
                self.assertEqual(batch.name, "legacy-batch")
                self.assertEqual(sync_job.status, "succeeded")
                self.assertEqual(exception.reason, "产品信息站点不唯一")
                self.assertEqual(exception.reason_code, "ambiguous_product_site")
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
                "reason_code",
            }.issubset(exception_columns)
        )
