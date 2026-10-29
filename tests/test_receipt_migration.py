"""旧库补齐累计实收字段时不修改已有批次或来源文件。"""

from sqlalchemy import inspect, text

from delivery_note.migrations.inbound_receipts import migrate
from tests.support.worker import WorkerCase


class ReceiptMigrationTests(WorkerCase):
    def test_sqlite_old_schema_upgrade_preserves_data_and_is_idempotent(self):
        batch = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "迁移前批次"},
        ).json()
        with self.app.state.database.engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE self_operated_batches DROP COLUMN receipt_snapshot")
            )
            connection.execute(
                text("ALTER TABLE batch_files DROP COLUMN receipt_context")
            )
            connection.execute(
                text("ALTER TABLE batch_files DROP COLUMN receipt_sites")
            )
        migrate(self.database_url)
        migrate(self.database_url)
        columns = {
            column["name"]: column
            for column in inspect(self.app.state.database.engine).get_columns(
                "batch_files"
            )
        }
        self.assertTrue(columns["receipt_context"]["nullable"])
        self.assertTrue(columns["receipt_sites"]["nullable"])
        restored = self.client.get(
            f"/api/batches/{batch['id']}", headers=self.headers
        ).json()
        self.assertEqual(restored["name"], "迁移前批次")
        self.assertIsNone(restored["receipt"])
