from tests.support.worker import WorkerCase
from datetime import datetime, timedelta
from pathlib import Path


from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)

from delivery_note.worker import (
    recover_stale_jobs,
    run_once,
)


class WorkerIntegrationTests(WorkerCase):
    def test_stale_job_recovers_and_failed_batch_persists_no_partial_results(self):
        valid = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 80
        )
        second = self.create_delivery(
            self.root / "260717-狂飙-B交货单-发货20箱.xlsx", 20
        )
        batch_id, job_id = self.create_batch([valid, second])

        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            job.status = "running"
            job.claim_token = "old-claim"
            job.heartbeat_at = datetime.utcnow() - timedelta(hours=2)
            sources = (
                session.query(BatchFile)
                .filter_by(batch_id=batch_id)
                .order_by(BatchFile.file_order)
                .all()
            )
            Path(sources[1].storage_path).write_bytes(b"not-an-excel-file")
            session.commit()
        recovered = recover_stale_jobs(
            self.database_url,
            stale_after=timedelta(minutes=30),
        )
        self.assertEqual(recovered, 1)
        with self.app.state.database.session() as session:
            self.assertIsNone(session.get(Job, job_id).claim_token)
        with self.assertLogs("delivery_note.worker", level="ERROR"):
            self.assertEqual(run_once(self.database_url, self.storage_root), job_id)

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            sources = session.query(BatchFile).filter_by(batch_id=batch_id).all()
            exceptions = (
                session.query(ExceptionRecord)
                .join(BatchFile)
                .filter(BatchFile.batch_id == batch_id)
                .all()
            )
            job = session.get(Job, job_id)
            self.assertEqual(batch.status, "failed")
            self.assertEqual(job.status, "failed")
            self.assertTrue(job.error_message)
            self.assertEqual(
                [
                    (source.import_total, source.manual_total, source.import_rows)
                    for source in sources
                ],
                [(0, 0, []), (0, 0, [])],
            )
            self.assertEqual(exceptions, [])

    def test_stale_recovery_only_scans_the_selected_queue(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        _batch_id, batch_job_id = self.create_batch([delivery])
        stale_at = datetime.utcnow() - timedelta(hours=2)
        with self.app.state.database.session() as session:
            batch_job = session.get(Job, batch_job_id)
            batch_job.status = "running"
            batch_job.attempts = 1
            batch_job.claim_token = "batch-claim"
            batch_job.heartbeat_at = stale_at
            purchase_job = PurchaseSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=1,
                claim_token="purchase-claim",
                heartbeat_at=stale_at,
            )
            inbound_job = SelfOperatedInboundSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=1,
                claim_token="inbound-claim",
                heartbeat_at=stale_at,
            )
            session.add_all([purchase_job, inbound_job])
            session.commit()
            purchase_job_id = purchase_job.id
            inbound_job_id = inbound_job.id

        recovered = recover_stale_jobs(
            self.database_url,
            stale_after=timedelta(minutes=30),
            queue="purchase-sync",
        )

        self.assertEqual(recovered, 1)
        with self.app.state.database.session() as session:
            self.assertEqual(session.get(Job, batch_job_id).status, "running")
            self.assertEqual(
                session.get(PurchaseSyncJob, purchase_job_id).status,
                "queued",
            )
            self.assertEqual(
                session.get(SelfOperatedInboundSyncJob, inbound_job_id).status,
                "running",
            )

    def test_stale_jobs_stop_at_retry_cap_and_batch_can_be_retried_manually(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        batch_id, batch_job_id = self.create_batch([delivery])
        stale_at = datetime.utcnow() - timedelta(hours=2)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "running"
            batch_job = session.get(Job, batch_job_id)
            batch_job.status = "running"
            batch_job.attempts = 3
            batch_job.claim_token = "batch-claim"
            batch_job.heartbeat_at = stale_at
            purchase_job = PurchaseSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=3,
                claim_token="purchase-claim",
                heartbeat_at=stale_at,
            )
            inbound_job = SelfOperatedInboundSyncJob(
                status="running",
                active_slot=1,
                created_by=1,
                attempts=3,
                claim_token="inbound-claim",
                heartbeat_at=stale_at,
            )
            session.add_all([purchase_job, inbound_job])
            session.commit()
            purchase_job_id = purchase_job.id
            inbound_job_id = inbound_job.id

        recovered = recover_stale_jobs(
            self.database_url,
            stale_after=timedelta(minutes=30),
            max_attempts=3,
        )

        self.assertEqual(recovered, 3)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch_job = session.get(Job, batch_job_id)
            purchase_job = session.get(PurchaseSyncJob, purchase_job_id)
            inbound_job = session.get(
                SelfOperatedInboundSyncJob,
                inbound_job_id,
            )
            self.assertEqual(batch.status, "failed")
            self.assertEqual(batch_job.status, "failed")
            self.assertIsNotNone(batch_job.finished_at)
            self.assertEqual(purchase_job.status, "failed")
            self.assertIsNone(purchase_job.active_slot)
            self.assertEqual(inbound_job.status, "failed")
            self.assertIsNone(inbound_job.active_slot)

        retried = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=self.headers,
        )
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["attempts"], 3)
        self.assertEqual(
            run_once(self.database_url, self.storage_root, queue="batch"),
            batch_job_id,
        )
        with self.app.state.database.session() as session:
            retried_job = session.get(Job, batch_job_id)
            self.assertEqual(retried_job.status, "succeeded")
            self.assertEqual(retried_job.attempts, 4)
