"""自营仓任务自动接续的集成测试。"""

from sqlalchemy import select

from delivery_note.web.models import AuditLog, Job
from delivery_note.worker import run_once
from tests.support.receipt_worker import ReceiptWorkerCase


class InboundJobChainTests(ReceiptWorkerCase):
    def test_preflight_compute_export_without_extra_requests(self):
        batch_id = self.create_receipt_batch()
        prepared = self.preflight(batch_id)
        self.assertEqual(prepared["status"], "queued")
        self.assertEqual(prepared["jobs"]["compute"]["status"], "queued")
        run_once(self.database_url, self.storage_root)
        computed = self.client.get(
            f"/api/batches/{batch_id}", headers=self.headers
        ).json()
        self.assertEqual(computed["status"], "succeeded")
        self.assertTrue(computed["summary"]["conserved"])
        self.assertEqual(computed["jobs"]["export"]["status"], "queued")
        run_once(self.database_url, self.storage_root)
        self.assertEqual(
            self.client.get(
                f"/api/batches/{batch_id}/download", headers=self.headers
            ).status_code,
            200,
        )
        with self.app.state.database.session() as session:
            audits = session.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(("queue_compute", "queue_export"))
                )
            ).all()
            self.assertEqual(len(audits), 2)
            self.assertTrue(all(item.user_id is None for item in audits))

    def test_blocked_preflight_does_not_queue_compute(self):
        batch_id = self.create_receipt_batch(cumulative=2, history=3)
        prepared = self.preflight(batch_id)
        self.assertEqual(prepared["status"], "draft")
        self.assertNotIn("compute", prepared["jobs"])

    def test_remaining_pending_still_queues_export(self):
        batch_id = self.create_receipt_batch(cumulative=50)
        self.preflight(batch_id)
        run_once(self.database_url, self.storage_root)
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.scalar(
                    select(Job).where(Job.batch_id == batch_id, Job.kind == "export")
                ).status,
                "queued",
            )

    def test_refresh_requeues_compute_after_preflight(self):
        batch_id = self.create_receipt_batch(cumulative=50)
        self.preflight(batch_id)
        run_once(self.database_url, self.storage_root)
        run_once(self.database_url, self.storage_root)
        refreshed = self.client.post(
            f"/api/batches/{batch_id}/receipts/refresh", headers=self.headers
        )
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        run_once(self.database_url, self.storage_root)
        batch = self.client.get(f"/api/batches/{batch_id}", headers=self.headers).json()
        self.assertEqual(batch["status"], "queued")
        self.assertEqual(batch["jobs"]["compute"]["status"], "queued")
