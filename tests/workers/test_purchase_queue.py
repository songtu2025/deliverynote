"""采购队列归属、公平领取、恢复和排队位置。"""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.manual_handling import recompute_disabled_reason
from delivery_note.web.models import Batch, Job, PurchaseSyncJob
from delivery_note.web.serializers import job_json
from delivery_note.workers.recovery import _recover_stale_jobs
from delivery_note.workers.scheduler import _run_once
from tests.support.postgres import PostgreSQLCase


class PurchaseQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        url = f"sqlite+pysqlite:///{Path(self.directory.name) / 'queues.db'}"
        migrate_schema(url)
        self.database = Database(url)
        self.addCleanup(self.database.dispose)
        self.started = datetime.utcnow() - timedelta(minutes=5)
        with self.database.session() as session:
            user, batch, _ = PostgreSQLCase.create_batch(session, "队列测试")
            self.batch_id = batch.id
            self.user_id = user.id
            session.commit()

    def add_job(self, kind: str, minutes: int = 0, status: str = "queued") -> int:
        with self.database.session() as session:
            source = session.get(Batch, self.batch_id)
            assert source is not None
            batch = Batch(
                name="排队批次",
                created_by=self.user_id,
                product_version_id=source.product_version_id,
                supplier_version_id=source.supplier_version_id,
            )
            session.add(batch)
            session.flush()
            job = Job(
                batch_id=batch.id,
                kind=kind,
                status=status,
                created_at=self.started + timedelta(minutes=minutes),
                claimed_at=self.started - timedelta(hours=2),
                attempts=1,
            )
            session.add(job)
            session.commit()
            return job.id

    def add_sync(self, minutes: int = 0, status: str = "queued") -> int:
        with self.database.session() as session:
            job = PurchaseSyncJob(
                created_by=self.user_id,
                status=status,
                created_at=self.started + timedelta(minutes=minutes),
                claimed_at=self.started - timedelta(hours=2),
                attempts=1,
            )
            session.add(job)
            session.commit()
            return job.id

    def test_batch_skips_snapshot_and_claims_interactive_jobs(self) -> None:
        snapshot = self.add_job("purchase_snapshot")
        for kind in ("prepare", "compute", "export"):
            identifier = self.add_job(kind)
            with patch("delivery_note.workers.scheduler._run_batch_job") as run:
                _run_once(self.database, self.directory.name, "batch")
                self.assertEqual(run.call_args.args[1][0], identifier)
        with self.database.session() as session:
            self.assertEqual(session.get_one(Job, snapshot).status, "queued")
        self.assertIsNone(_run_once(self.database, self.directory.name, "batch"))

    def test_purchase_queue_uses_oldest_created_across_tables(self) -> None:
        for sync_first in (False, True):
            with self.subTest(sync_first=sync_first):
                sync_id = self.add_sync(0 if sync_first else 1)
                snapshot_id = self.add_job("purchase_snapshot", 1 if sync_first else 0)
                with (
                    patch("delivery_note.workers.scheduler._run_batch_job") as snapshot,
                    patch("delivery_note.workers.scheduler._run_purchase_job") as sync,
                ):
                    _run_once(self.database, self.directory.name, "purchase-sync")
                    first = sync if sync_first else snapshot
                    second = snapshot if sync_first else sync
                    self.assertEqual(first.call_count, 1)
                    second.assert_not_called()
                    _run_once(self.database, self.directory.name, "purchase-sync")
                    self.assertEqual(second.call_count, 1)
                    self.assertEqual(snapshot.call_args.args[1][0], snapshot_id)
                    self.assertEqual(sync.call_args.args[1][0], sync_id)

    def test_all_still_claims_both_job_tables(self) -> None:
        self.add_job("purchase_snapshot")
        self.add_job("compute")
        self.add_sync()
        with (
            patch("delivery_note.workers.scheduler._run_batch_job") as batch,
            patch("delivery_note.workers.scheduler._run_purchase_job") as sync,
        ):
            for _ in range(3):
                _run_once(self.database, self.directory.name, "all")
            self.assertEqual(batch.call_count, 2)
            sync.assert_called_once()

    def test_recovery_uses_new_queue_ownership(self) -> None:
        compute_id = self.add_job("compute", status="running")
        snapshot_id = self.add_job("purchase_snapshot", status="running")
        self.add_sync(status="running")
        self.assertEqual(_recover_stale_jobs(self.database, queue="batch"), 1)
        with self.database.session() as session:
            self.assertEqual(session.get_one(Job, compute_id).status, "queued")
            self.assertEqual(session.get_one(Job, snapshot_id).status, "running")
        self.assertEqual(_recover_stale_jobs(self.database, queue="purchase-sync"), 2)
        with self.database.session() as session:
            self.assertEqual(session.get_one(Job, snapshot_id).status, "queued")

    def test_queue_position_counts_only_preceding_active_jobs(self) -> None:
        self.add_job("purchase_snapshot")
        self.add_job("prepare", status="running")
        self.add_job("compute", status="failed")
        self.add_job("export")
        current = self.add_job("compute")
        self.add_job("compute")
        with self.database.session() as session:
            self.assertEqual(
                job_json(session.get_one(Job, current))["queue_position"], 2
            )

    def test_snapshot_position_includes_older_sync_but_not_batch_jobs(self) -> None:
        self.add_job("compute")
        self.add_sync(status="running")
        self.add_sync()
        snapshot_id = self.add_job("purchase_snapshot")
        later_id = self.add_job("purchase_snapshot", 1)
        with self.database.session() as session:
            self.assertEqual(
                job_json(session.get_one(Job, snapshot_id))["queue_position"], 1
            )
            self.assertEqual(
                job_json(session.get_one(Job, later_id))["queue_position"], 3
            )

    def test_nonqueued_job_does_not_include_queue_position(self) -> None:
        identifier = self.add_job("export", status="succeeded")
        with self.database.session() as session:
            self.assertNotIn(
                "queue_position", job_json(session.get_one(Job, identifier))
            )

    def test_purchase_snapshot_does_not_block_manual_recalculation(self) -> None:
        identifier = self.add_job("purchase_snapshot", status="running")
        with self.database.session() as session:
            job = session.get_one(Job, identifier)
            batch = session.get_one(Batch, job.batch_id)
            batch.status = "succeeded"
            self.assertIsNone(recompute_disabled_reason(session, batch))
            job.kind = "compute"
            self.assertEqual(
                recompute_disabled_reason(session, batch),
                "后台任务进行中，请完成后再修改输入",
            )
