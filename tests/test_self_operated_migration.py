from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect, text

from delivery_note.migrations.self_operated_optional_versions import (
    migrate as migrate_self_operated_optional_versions,
)
from delivery_note.web.database import Database
from delivery_note.web.models import (
    InputVersion,
    User,
)


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
