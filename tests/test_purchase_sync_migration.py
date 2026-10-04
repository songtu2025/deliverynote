from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect, text

from delivery_note.migrations.purchase_sync_optional_versions import (
    migrate as migrate_purchase_sync_optional_versions,
)
from delivery_note.web.database import Database
from delivery_note.web.models import (
    InputVersion,
    PurchaseSyncJob,
    User,
)


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
