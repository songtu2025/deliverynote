from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect, text

from delivery_note.migrations.overreceipt_rules import migrate
from delivery_note.migrations.purchase_sync_optional_versions import (
    migrate as migrate_purchase_sync_optional_versions,
)
from delivery_note.migrations.runner import migrate_schema
from delivery_note.migrations.self_operated_optional_versions import (
    migrate as migrate_self_operated_optional_versions,
)
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Base,
    Batch,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputVersion,
    OverreceiptRuleVersion,
    PurchaseSyncJob,
    User,
)


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


class SelfOperatedOptionalVersionMigrationTests(unittest.TestCase):
    def test_migration_preserves_batches_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'migration.db'}"
            database = Database(database_url)
            database.create_schema()
            try:
                with database.session() as session:
                    user = User(
                        username="admin",
                        password_hash="test",
                        role="admin",
                    )
                    session.add(user)
                    session.flush()
                    version_ids = {}
                    for kind in (
                        "purchase",
                        "product",
                        "supplier",
                        "position",
                        "template",
                    ):
                        version = InputVersion(
                            kind=kind,
                            name=f"{kind}-v1",
                            original_name=f"{kind}.xlsx",
                            storage_path=f"/{kind}.xlsx",
                            active=True,
                            created_by=user.id,
                        )
                        session.add(version)
                        session.flush()
                        version_ids[kind] = version.id
                    session.commit()
                    user_id = user.id

                connection = database.engine.connect()
                try:
                    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                    connection.commit()
                    with connection.begin():
                        connection.execute(text("DROP TABLE batches"))
                        connection.execute(
                            text(
                                """
                            CREATE TABLE batches (
                                id INTEGER NOT NULL,
                                name VARCHAR(200) NOT NULL,
                                status VARCHAR(30) NOT NULL,
                                created_by INTEGER NOT NULL,
                                purchase_version_id INTEGER NOT NULL,
                                product_version_id INTEGER NOT NULL,
                                supplier_version_id INTEGER NOT NULL,
                                position_version_id INTEGER NOT NULL,
                                template_version_id INTEGER NOT NULL,
                                zip_path TEXT,
                                error_message TEXT,
                                created_at DATETIME NOT NULL,
                                updated_at DATETIME NOT NULL,
                                PRIMARY KEY (id),
                                FOREIGN KEY(created_by) REFERENCES users (id),
                                FOREIGN KEY(purchase_version_id)
                                    REFERENCES input_versions (id),
                                FOREIGN KEY(product_version_id)
                                    REFERENCES input_versions (id),
                                FOREIGN KEY(supplier_version_id)
                                    REFERENCES input_versions (id),
                                FOREIGN KEY(position_version_id)
                                    REFERENCES input_versions (id),
                                FOREIGN KEY(template_version_id)
                                    REFERENCES input_versions (id)
                            )
                            """
                            )
                        )
                        connection.execute(
                            text(
                                """
                            INSERT INTO batches (
                                id, name, status, created_by,
                                purchase_version_id, product_version_id,
                                supplier_version_id, position_version_id,
                                template_version_id, created_at, updated_at
                            ) VALUES (
                                1, 'existing', 'draft', :created_by,
                                :purchase, :product, :supplier, :position,
                                :template, '2026-08-21 00:00:00',
                                '2026-08-21 00:00:00'
                            )
                            """
                            ),
                            {
                                "created_by": user_id,
                                **version_ids,
                            },
                        )
                        connection.execute(
                            text("CREATE INDEX ix_batches_status ON batches (status)")
                        )
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                finally:
                    connection.close()
            finally:
                database.dispose()

            migrate_self_operated_optional_versions(database_url)
            migrate_self_operated_optional_versions(database_url)

            database = Database(database_url)
            try:
                columns = {
                    column["name"]: column
                    for column in inspect(database.engine).get_columns("batches")
                }
                with database.engine.connect() as connection:
                    existing = connection.execute(
                        text(
                            "SELECT name, product_version_id, supplier_version_id "
                            "FROM batches WHERE id = 1"
                        )
                    ).one()
            finally:
                database.dispose()

        for column in (
            "purchase_version_id",
            "position_version_id",
            "template_version_id",
        ):
            self.assertTrue(columns[column]["nullable"])
        self.assertFalse(columns["product_version_id"]["nullable"])
        self.assertFalse(columns["supplier_version_id"]["nullable"])
        self.assertEqual(existing.name, "existing")
        self.assertEqual(existing.product_version_id, version_ids["product"])
        self.assertEqual(existing.supplier_version_id, version_ids["supplier"])


class PurchaseSyncOptionalVersionMigrationTests(unittest.TestCase):
    def test_migration_preserves_jobs_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            database_url = f"sqlite+pysqlite:///{Path(directory) / 'migration.db'}"
            database = Database(database_url)
            database.create_schema()
            try:
                with database.session() as session:
                    user = User(
                        username="admin",
                        password_hash="test",
                        role="admin",
                    )
                    session.add(user)
                    session.flush()
                    product = InputVersion(
                        kind="product",
                        name="product-v1",
                        original_name="product.xlsx",
                        storage_path="/product.xlsx",
                        active=True,
                        created_by=user.id,
                    )
                    supplier = InputVersion(
                        kind="supplier",
                        name="supplier-v1",
                        original_name="supplier.xlsx",
                        storage_path="/supplier.xlsx",
                        active=True,
                        created_by=user.id,
                    )
                    session.add_all([product, supplier])
                    session.commit()
                    user_id = user.id
                    product_id = product.id
                    supplier_id = supplier.id

                connection = database.engine.connect()
                try:
                    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                    connection.commit()
                    with connection.begin():
                        connection.execute(text("DROP TABLE purchase_sync_jobs"))
                        connection.execute(
                            text(
                                """
                            CREATE TABLE purchase_sync_jobs (
                                id INTEGER NOT NULL,
                                status VARCHAR(20) NOT NULL,
                                active_slot INTEGER,
                                created_by INTEGER NOT NULL,
                                base_version_id INTEGER,
                                product_version_id INTEGER NOT NULL,
                                supplier_version_id INTEGER NOT NULL,
                                candidate_version_id INTEGER,
                                total_orders INTEGER NOT NULL,
                                processed_orders INTEGER NOT NULL,
                                raw_detail_count INTEGER NOT NULL,
                                eligible_detail_count INTEGER NOT NULL,
                                filtered_detail_count INTEGER NOT NULL,
                                current_order TEXT,
                                issues JSON NOT NULL,
                                diff JSON NOT NULL,
                                attempts INTEGER NOT NULL,
                                claim_token VARCHAR(64),
                                claimed_at DATETIME,
                                heartbeat_at DATETIME,
                                finished_at DATETIME,
                                error_message TEXT,
                                created_at DATETIME NOT NULL,
                                PRIMARY KEY (id),
                                CONSTRAINT uq_active_purchase_sync_job
                                    UNIQUE (active_slot),
                                FOREIGN KEY(created_by) REFERENCES users (id),
                                FOREIGN KEY(product_version_id)
                                    REFERENCES input_versions (id),
                                FOREIGN KEY(supplier_version_id)
                                    REFERENCES input_versions (id)
                            )
                            """
                            )
                        )
                        connection.execute(
                            text(
                                """
                            INSERT INTO purchase_sync_jobs (
                                id, status, created_by, product_version_id,
                                supplier_version_id, total_orders,
                                processed_orders, raw_detail_count,
                                eligible_detail_count, filtered_detail_count,
                                issues, diff, attempts, created_at
                            ) VALUES (
                                1, 'succeeded', :created_by, :product,
                                :supplier, 129, 129, 9437, 4196, 5241,
                                '[]', '{}', 1, '2026-08-25 00:00:00'
                            )
                            """
                            ),
                            {
                                "created_by": user_id,
                                "product": product_id,
                                "supplier": supplier_id,
                            },
                        )
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                finally:
                    connection.close()
            finally:
                database.dispose()

            migrate_purchase_sync_optional_versions(database_url)
            migrate_purchase_sync_optional_versions(database_url)

            database = Database(database_url)
            try:
                columns = {
                    column["name"]: column
                    for column in inspect(database.engine).get_columns(
                        PurchaseSyncJob.__tablename__
                    )
                }
                with database.engine.connect() as connection:
                    existing = connection.execute(
                        text(
                            "SELECT status, product_version_id, "
                            "supplier_version_id FROM purchase_sync_jobs "
                            "WHERE id = 1"
                        )
                    ).one()
            finally:
                database.dispose()

        self.assertTrue(columns["product_version_id"]["nullable"])
        self.assertTrue(columns["supplier_version_id"]["nullable"])
        self.assertEqual(existing.status, "succeeded")
        self.assertEqual(existing.product_version_id, product_id)
        self.assertEqual(existing.supplier_version_id, supplier_id)


if __name__ == "__main__":
    unittest.main()
