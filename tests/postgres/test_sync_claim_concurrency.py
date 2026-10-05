from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import cast

from sqlalchemy import event

from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.models import PurchaseSyncJob, SelfOperatedInboundSyncJob
from delivery_note.workers.leases import _claim_sync_job
from delivery_note.workers.sync_models import SyncJob, SyncJobModel
from tests.support.postgres import PostgreSQLCase


def concurrent_claims(
    url: str, model: SyncJobModel
) -> tuple[tuple[int, str] | None, tuple[int, str] | None]:
    first_database, second_database = Database(url), Database(url)
    updating, release = Event(), Event()

    def pause_update(
        _connection: object, _cursor: object, statement: str, *_args: object
    ) -> None:
        if (
            statement.lstrip()
            .upper()
            .startswith(f"UPDATE {model.__tablename__.upper()}")
        ):
            updating.set()
            if not release.wait(timeout=10):
                raise TimeoutError("等待第二个同步 Worker 领取超时")

    event.listen(first_database.engine, "before_cursor_execute", pause_update)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(_claim_sync_job, first_database, model)
            try:
                if not updating.wait(timeout=10):
                    raise TimeoutError("第一个同步 Worker 未进入领取状态更新")
                second = _claim_sync_job(second_database, model)
            finally:
                release.set()
            return first.result(timeout=10), second
    finally:
        release.set()
        first_database.dispose()
        second_database.dispose()


class SyncClaimConcurrencyTests(PostgreSQLCase):
    def test_both_sync_queues_skip_locked_task_and_claim_it_once(self) -> None:
        migrate_schema(self.database_url)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                user, _, _ = self.create_batch(session, "同步领取并发")
                user_id = user.id
                session.commit()
            models: tuple[SyncJobModel, ...] = (
                PurchaseSyncJob,
                SelfOperatedInboundSyncJob,
            )
            for model in models:
                with self.subTest(model=model.__name__):
                    with database.session() as session:
                        job = model(status="queued", created_by=user_id, active_slot=1)
                        session.add(job)
                        session.commit()
                        job_id = job.id
                    first, second = concurrent_claims(self.database_url, model)
                    self.assertIsNotNone(first)
                    assert first is not None
                    self.assertEqual(first[0], job_id)
                    self.assertIsNone(second)
                    with database.session() as session:
                        current = cast(SyncJob | None, session.get(model, job_id))
                        assert current is not None
                        self.assertEqual(
                            (current.status, current.attempts), ("running", 1)
                        )
                        self.assertEqual(current.claim_token, first[1])
                        self.assertEqual(current.claimed_at, current.heartbeat_at)
        finally:
            database.dispose()
