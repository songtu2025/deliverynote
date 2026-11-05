"""统一调整的原子校验、审计与一次排队。"""

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


class AdjustmentTests(ExceptionTransferCase):
    def setUp(self):
        super().setUp()
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            profile = session.get(SelfOperatedBatch, batch.id)
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == batch.id)
            )
            self.file_id = source.id
            profile.receipt_snapshot = {
                "signature": receipt_signature(batch, profile, [source]),
                "summary": {"issue_count": 0},
            }
            source.receipt_context = {
                "issue_count": 0,
                "rows": [
                    {
                        "sku": "SKU-A",
                        "original_site": "US",
                        "candidates": ["AMAZON:SEEKWAY:US"],
                    }
                ],
            }
            session.commit()

    def allowance(self, **changes):
        return {
            "supplier_code": "GYS-023",
            "sku": "SKU-A",
            "full_site": "AMAZON:SEEKWAY:US",
            "quantity": 3,
            **changes,
        }

    def site(self, **changes):
        return {
            "file_id": self.file_id,
            "sku": "SKU-A",
            "original_site": "US",
            "full_site": "AMAZON:SEEKWAY:US",
            **changes,
        }

    def save(self, payload):
        return self.client.put(
            f"/api/batches/{self.batch_id}/adjustments",
            json=payload,
            headers=self.headers,
        )

    def test_allowances_queue_one_compute_and_audit_each_change(self):
        self.add_source(sku="SKU-B", order=2)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            profile = session.get(SelfOperatedBatch, batch.id)
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch.id)
            ).all()
            profile.receipt_snapshot = {
                **profile.receipt_snapshot,
                "signature": receipt_signature(batch, profile, sources),
            }
            for source in sources:
                source.receipt_context = {"issue_count": 0}
            session.commit()
        response = self.save(
            {
                "allowances": [self.allowance(), self.allowance(sku="SKU-B")],
                "reason": "  确认  ",
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["jobs"]["compute"]["status"], "queued")
        self.assertEqual(len(response.json()["manual_allowances"]), 2)
        self.assertEqual(response.json()["manual_allowances"][0]["reason"], "确认")
        with self.app.state.database.session() as session:
            for action, count in (("queue_compute", 1), ("save_manual_allowance", 2)):
                self.assertEqual(
                    session.scalar(
                        select(func.count())
                        .select_from(AuditLog)
                        .where(AuditLog.action == action)
                    ),
                    count,
                )

    def test_sites_and_allowances_queue_one_prepare_with_snapshot_retained(self):
        response = self.save({"allowances": [self.allowance()], "sites": [self.site()]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["jobs"]["prepare"]["status"], "queued")
        self.assertNotIn("compute", response.json()["jobs"])
        with self.app.state.database.session() as session:
            profile = session.get(SelfOperatedBatch, self.batch_id)
            source = session.get(BatchFile, self.file_id)
            self.assertTrue(profile.receipt_snapshot["signature"])
            self.assertEqual(source.receipt_sites, {"SKU-A\tUS": "AMAZON:SEEKWAY:US"})
            self.assertEqual(profile.manual_handling["allowances"][0]["quantity"], 3)
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "choose_receipt_site")
                ),
                1,
            )

    def test_invalid_input_never_saves_any_changes(self):
        payloads = [
            {
                "allowances": [self.allowance()],
                "sites": [self.site(full_site="INVALID")],
            },
            {"allowances": [self.allowance(sku="MISSING")], "sites": [self.site()]},
            {"allowances": [self.allowance(), self.allowance()]},
            {"sites": [self.site(), self.site()]},
            {"allowances": [self.allowance(quantity=-1)]},
            {"sites": [self.site(file_id=99999)]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertIn(self.save(payload).status_code, (400, 404, 422))
                with self.app.state.database.session() as session:
                    self.assertFalse(
                        session.get(SelfOperatedBatch, self.batch_id).manual_handling
                    )
                    self.assertFalse(session.get(BatchFile, self.file_id).receipt_sites)
                    self.assertIsNotNone(
                        session.get(ExceptionRecord, self.exception_id)
                    )
                    self.assertIsNone(
                        session.scalar(select(Job).where(Job.batch_id == self.batch_id))
                    )

    def test_empty_unauthenticated_delivery_and_transferred_requests_rejected(self):
        self.assertEqual(self.save({}).status_code, 422)
        self.assertEqual(self.save({"allowances": [], "sites": []}).status_code, 422)
        anonymous = type(self.client)(self.app)
        try:
            result = anonymous.put(
                f"/api/batches/{self.batch_id}/adjustments",
                json={"sites": [self.site()]},
            )
            self.assertEqual(result.status_code, 401)
        finally:
            anonymous.close()
        self.assertEqual(self.transfer(1).status_code, 201)
        self.complete_export()
        for payload in ({"allowances": [self.allowance()]}, {"sites": [self.site()]}):
            self.assertIn("先处理超收再转交", self.save(payload).text)
        with self.app.state.database.session() as session:
            session.delete(session.get(SelfOperatedBatch, self.batch_id))
            session.commit()
        self.assertEqual(self.save({"allowances": [self.allowance()]}).status_code, 400)
