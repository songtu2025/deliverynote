"""旧库人工处理字段升级保留数据，重复执行不改变结果。"""

from sqlalchemy import inspect, text

from delivery_note.migrations.self_operated_manual_handling import migrate
from delivery_note.migrations.runner import MIGRATIONS
from tests.support.exception_transfers import ExceptionTransferCase


class ManualHandlingMigrationTests(ExceptionTransferCase):
    def test_old_schema_upgrade_preserves_data_and_is_idempotent(self):
        self.assertIn(migrate, MIGRATIONS)
        engine = self.app.state.database.engine
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE self_operated_batches DROP COLUMN manual_handling")
            )
            connection.execute(
                text("ALTER TABLE exceptions DROP COLUMN offline_quantity")
            )
            connection.execute(text("ALTER TABLE exceptions DROP COLUMN offline_note"))
        url = str(engine.url)
        migrate(url)
        migrate(url)
        columns = {
            column["name"] for column in inspect(engine).get_columns("exceptions")
        }
        self.assertTrue({"offline_quantity", "offline_note"} <= columns)
        row = self.records()[0]
        self.assertEqual(row["manual_quantity"], 8)
        self.assertEqual((row["offline_quantity"], row["offline_note"]), (0, ""))
