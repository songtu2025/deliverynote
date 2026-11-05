"""自营仓自动导出排队、幂等和人工处理后的数量口径。"""

from sqlalchemy import func, select

from delivery_note.web.job_queue import queue_inbound_export
from delivery_note.web.models import (
    AuditLog,
    Batch,
    ExceptionRecord,
    Job,
    SelfOperatedBatch,
)
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

    def test_partial_offline_does_not_export_all_offline_queues_export(self):
        saved = self.offline(3, "  备注  ")
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["offline_note"], "备注")
        with self.app.state.database.session() as session:
            self.assertIsNone(self.export_job(session))
        saved = self.offline(8)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["status"], "resolved")
        with self.app.state.database.session() as session:
            self.assertEqual(self.export_job(session).status, "queued")
            log = session.scalar(
                select(AuditLog).where(AuditLog.action == "save_offline_handling")
            )
            self.assertIsNotNone(log.user_id)
            self.assertIn("quantity", log.details)

    def test_transfer_finishes_remaining_and_automatically_exports(self):
        self.assertEqual(self.offline(3).status_code, 200)
        transferred = self.transfer(5)
        self.assertEqual(transferred.status_code, 201, transferred.text)
        with self.app.state.database.session() as session:
            self.assertEqual(self.export_job(session).status, "queued")
            self.assertEqual(
                session.get(ExceptionRecord, self.exception_id).status, "resolved"
            )

    def test_active_and_succeeded_export_not_requeued_stale_export_is(self):
        self.assertEqual(self.offline(8).status_code, 200)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            export = self.export_job(session)
            for status in ("queued", "running", "succeeded"):
                export.status = status
                export.output_path = "synthetic.xlsx"
                queue_inbound_export(session, batch)
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
            queue_inbound_export(session, batch)
            self.assertEqual(export.status, "queued")
            self.assertIsNone(export.output_path)

    def test_revoke_after_export_invalidates_result_and_keeps_conservation(self):
        self.assertEqual(self.offline(8).status_code, 200)
        with self.app.state.database.session() as session:
            self.export_job(session).status = "succeeded"
            session.commit()
        revoked = self.offline(0)
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["status"], "pending")
        with self.app.state.database.session() as session:
            self.assertEqual(self.export_job(session).status, "stale")
        summary = self.client.get(
            f"/api/batches/{self.batch_id}", headers=self.headers
        ).json()["summary"]
        self.assertEqual(
            summary["delivery_total"], summary["import_total"] + summary["manual_total"]
        )
        self.assertTrue(summary["conserved"])

    def test_delivery_workflow_and_failed_batch_do_not_auto_export(self):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            session.get(ExceptionRecord, self.exception_id).status = "resolved"
            batch.status = "failed"
            queue_inbound_export(session, batch)
            self.assertIsNone(self.export_job(session))
            batch.status = "succeeded"
            session.delete(session.get(SelfOperatedBatch, self.batch_id))
            session.flush()
            session.expire_all()
            queue_inbound_export(session, session.get(Batch, self.batch_id))
            self.assertIsNone(self.export_job(session))
