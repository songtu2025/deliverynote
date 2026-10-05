from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from typing import cast

from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Batch,
    Job,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)
from delivery_note.workers.leases import _claim_job, _claim_sync_job
from delivery_note.workers.sync_models import SyncJob
from tests.support.postgres import PostgreSQLCase


class ClaimStateTests(unittest.TestCase):
    def test_all_queues_refresh_claim_state_and_keep_batch_side_effects(self) -> None:
        with ExitStack() as stack:
            directory = stack.enter_context(TemporaryDirectory())
            url = f"sqlite+pysqlite:///{Path(directory) / 'claims.db'}"
            migrate_schema(url)
            database = Database(url)
            stack.callback(database.dispose)
            old_time = datetime.utcnow() - timedelta(hours=1)
            with database.session() as session:
                user, batch, _ = PostgreSQLCase.create_batch(session, "领取状态测试")
                batch.status, batch.error_message = "failed", "上一次失败"
                jobs: list[Job | SyncJob] = [
                    Job(batch_id=batch.id, kind="compute"),
                    Job(batch_id=batch.id, kind="export"),
                    PurchaseSyncJob(created_by=user.id),
                    SelfOperatedInboundSyncJob(created_by=user.id),
                ]
                for job in jobs:
                    job.status, job.attempts = "queued", 2
                    job.claim_token, job.error_message = "old-token", "上一次失败"
                    job.claimed_at = job.heartbeat_at = job.finished_at = old_time
                session.add_all(jobs)
                session.commit()
                batch_id = batch.id
            for job in jobs:
                with self.subTest(model=type(job).__name__, job_id=job.id):
                    before = datetime.utcnow()
                    claim = (
                        _claim_job(database)
                        if isinstance(job, Job)
                        else _claim_sync_job(database, type(job))
                    )
                    after = datetime.utcnow()
                    self.assertIsNotNone(claim)
                    assert claim is not None
                    self.assertEqual(claim[0], job.id)
                    with database.session() as session:
                        current = cast(
                            Job | SyncJob | None, session.get(type(job), job.id)
                        )
                        assert current is not None and current.claimed_at is not None
                        self.assertEqual(
                            (current.status, current.attempts), ("running", 3)
                        )
                        self.assertEqual(current.claim_token, claim[-1])
                        self.assertRegex(current.claim_token or "", r"^[0-9a-f]{32}$")
                        self.assertNotEqual(current.claim_token, "old-token")
                        self.assertIsNone(current.error_message)
                        self.assertLessEqual(before, current.claimed_at)
                        self.assertLessEqual(current.claimed_at, after)
                        self.assertEqual(current.claimed_at, current.heartbeat_at)
                        self.assertEqual(current.finished_at, old_time)
                        batch = session.get(Batch, batch_id)
                        assert batch is not None
                        if isinstance(job, Job) and job.kind == "compute":
                            self.assertEqual(
                                (batch.status, batch.error_message), ("running", None)
                            )
                            batch.status, batch.error_message = (
                                "computed",
                                "保留计算结果",
                            )
                            session.commit()
                        else:
                            self.assertEqual(
                                (batch.status, batch.error_message),
                                ("computed", "保留计算结果"),
                            )
