from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect, text

from delivery_note.migrations.overreceipt_rules import migrate
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Base,
    BatchOverreceiptRule,
    ExceptionRecord,
    OverreceiptRuleVersion,
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
                    if table not in {
                        OverreceiptRuleVersion.__table__,
                        BatchOverreceiptRule.__table__,
                        ExceptionRecord.__table__,
                    }
                ]
                Base.metadata.create_all(database.engine, tables=existing_tables)
                with database.engine.begin() as connection:
                    connection.execute(text(
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
                    ))
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
