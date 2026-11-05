"""批量追加额度的原子保存与单条请求兼容。"""

from sqlalchemy import func, select

from delivery_note.web.models import (
    AuditLog,
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    SelfOperatedBatch,
)
from delivery_note.web.receipt_state import receipt_signature
from tests.support.exception_transfers import ExceptionTransferCase


class ManualAllowanceBatchTests(ExceptionTransferCase):
    def setUp(self):
        super().setUp()
        self.second_id = self.add_source(sku="SKU-B", order=2)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            profile = session.get(SelfOperatedBatch, self.batch_id)
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch.id)
            ).all()
            profile.receipt_snapshot = {
                "signature": receipt_signature(batch, profile, sources),
                "summary": {"issue_count": 0},
            }
            for source in sources:
                source.receipt_context = {"issue_count": 0, "rows": [{}]}
            session.commit()

    def item(self, sku="SKU-A", **changes):
        return {
            "supplier_code": "GYS-023",
            "sku": sku,
            "full_site": "AMAZON:SEEKWAY:US",
            "quantity": 8,
            **changes,
        }

    def save(self, payload):
        return self.client.put(
            f"/api/batches/{self.batch_id}/manual-allowances",
            headers=self.headers,
            json=payload,
        )

    def test_batch_saves_all_and_queues_compute_once_with_optional_reason(self):
        result = self.save({"items": [self.item(reason="  "), self.item("SKU-B")]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()["manual_allowances"]), 2)
        self.assertEqual(result.json()["manual_allowances"][0]["reason"], "")
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "queue_compute")
                ),
                1,
            )

    def test_single_payload_remains_compatible(self):
        result = self.save(self.item(reason="  确认  "))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["manual_allowances"][0]["reason"], "确认")

    def test_any_invalid_item_rolls_back_inputs_results_and_job(self):
        for invalid in (self.item("MISSING"), self.item("SKU-B", quantity=-1)):
            with self.subTest(invalid=invalid):
                result = self.save({"items": [self.item(), invalid]})
                self.assertIn(result.status_code, (400, 422), result.text)
                with self.app.state.database.session() as session:
                    self.assertFalse(
                        session.get(SelfOperatedBatch, self.batch_id).manual_handling
                    )
                    self.assertIsNotNone(
                        session.get(ExceptionRecord, self.exception_id)
                    )
                    self.assertIsNone(
                        session.scalar(select(Job).where(Job.batch_id == self.batch_id))
                    )

    def test_empty_batch_is_rejected(self):
        self.assertEqual(self.save({"items": []}).status_code, 422)
