from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import inspect

from delivery_note.migrations.overreceipt_rules import migrate
from delivery_note.web.database import Database
from delivery_note.web.models import Base, BatchOverreceiptRule, OverreceiptRuleVersion


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
                    }
                ]
                Base.metadata.create_all(database.engine, tables=existing_tables)
            finally:
                database.dispose()

            migrate(database_url)
            migrate(database_url)

            database = Database(database_url)
            try:
                tables = set(inspect(database.engine).get_table_names())
            finally:
                database.dispose()
        self.assertIn("overreceipt_rule_versions", tables)
        self.assertIn("batch_overreceipt_rules", tables)


if __name__ == "__main__":
    unittest.main()
