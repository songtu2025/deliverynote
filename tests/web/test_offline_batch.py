"""批量线下处理一次提交、整体回滚并只重新生成一次结果。"""

from sqlalchemy import func, select

from delivery_note.web.models import AuditLog, Job
from tests.support.exception_transfers import ExceptionTransferCase


class OfflineBatchTests(ExceptionTransferCase):
    def batch_offline(self, items):
        return self.client.put(
            f"/api/batches/{self.batch_id}/offline-handling",
            headers=self.headers,
            json={"items": items},
        )

    def test_batch_offline_saves_all_and_queues_export_once(self):
        response = self.batch_offline(
            [{"exception_id": self.exception_id, "quantity": 3, "note": "统一"}]
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.records()[0]["offline_quantity"], 3)
        with self.app.state.database.session() as session:
            export = session.scalar(
                select(Job).where(Job.batch_id == self.batch_id, Job.kind == "export")
            )
            self.assertEqual(export.status, "queued")
            queued = session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "queue_export")
            )
            self.assertEqual(queued, 1)

    def test_batch_offline_rolls_back_when_any_item_fails(self):
        invalid = self.batch_offline(
            [
                {"exception_id": self.exception_id, "quantity": 3, "note": ""},
                {"exception_id": self.exception_id + 9999, "quantity": 1, "note": ""},
            ]
        )
        self.assertEqual(invalid.status_code, 409, invalid.text)
        self.assertEqual(self.records()[0]["offline_quantity"], 0)
        duplicate = self.batch_offline(
            [
                {"exception_id": self.exception_id, "quantity": 1, "note": ""},
                {"exception_id": self.exception_id, "quantity": 1, "note": ""},
            ]
        )
        self.assertEqual(duplicate.status_code, 400, duplicate.text)
        self.assertEqual(self.batch_offline([]).status_code, 422)
