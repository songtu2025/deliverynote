"""任务接续幂等，人工收尾不触发导出或改变结果状态。"""

from sqlalchemy import func, select

from delivery_note.web.job_queue import queue_followup_job
from delivery_note.web.models import AuditLog, Batch, ExceptionRecord, Job
from tests.support.exception_transfers import ExceptionTransferCase


class InboundExportQueueTests(ExceptionTransferCase):
    def export_job(self, session):
        return session.scalar(
            select(Job).where(Job.batch_id == self.batch_id, Job.kind == "export")
        )

    def offline(self, quantity, note=""):
        return self.client.put(
            f"/api/exceptions/{self.exception_id}/offline-handling",
            headers=self.headers,
            json={"quantity": quantity, "note": note},
        )

    def test_partial_and_full_offline_never_queue_export(self):
        for quantity in (3, 8):
            saved = self.offline(quantity, "  备注  ")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["offline_note"], "备注")
            with self.app.state.database.session() as session:
                self.assertIsNone(self.export_job(session))
        self.assertEqual(saved.json()["status"], "resolved")
        with self.app.state.database.session() as session:
            log = session.scalar(
                select(AuditLog).where(AuditLog.action == "save_offline_handling")
            )
            self.assertIsNotNone(log.user_id)
            self.assertIn("quantity", log.details)

    def test_transfer_finishes_remaining_without_queueing_export(self):
        self.assertEqual(self.offline(3).status_code, 200)
        transferred = self.transfer(5)
        self.assertEqual(transferred.status_code, 201, transferred.text)
        with self.app.state.database.session() as session:
            self.assertIsNone(self.export_job(session))
            self.assertEqual(
                session.get(ExceptionRecord, self.exception_id).status, "resolved"
            )

    def test_followup_is_idempotent_and_requeues_stale_export(self):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            export = queue_followup_job(session, batch, "export")
            for status in ("queued", "running", "succeeded"):
                export.status = status
                export.output_path = "synthetic.xlsx"
                queue_followup_job(session, batch, "export")
                self.assertEqual(export.status, status)
                self.assertEqual(export.output_path, "synthetic.xlsx")
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "queue_export")
                ),
                1,
            )
            export.status = "stale"
            queue_followup_job(session, batch, "export")
            self.assertEqual(export.status, "queued")
            self.assertIsNone(export.output_path)

    def test_revoke_after_export_preserves_result_and_conservation(self):
        self.assertEqual(self.offline(8).status_code, 200)
        with self.app.state.database.session() as session:
            session.add(
                Job(
                    batch_id=self.batch_id,
                    kind="export",
                    status="succeeded",
                    output_path="synthetic.xlsx",
                )
            )
            session.commit()
        revoked = self.offline(0)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["status"], "pending")
        with self.app.state.database.session() as session:
            self.assertEqual(self.export_job(session).status, "succeeded")
            self.assertEqual(self.export_job(session).output_path, "synthetic.xlsx")
        summary = self.client.get(
            f"/api/batches/{self.batch_id}", headers=self.headers
        ).json()["summary"]
        self.assertEqual(
            summary["delivery_total"], summary["import_total"] + summary["manual_total"]
        )
        self.assertTrue(summary["conserved"])
