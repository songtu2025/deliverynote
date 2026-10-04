from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from delivery_note.migrations.runner import migrate_schema
from delivery_note.web.database import Database
from delivery_note.web.models import (
    InputVersion,
    Job,
    User,
)
from delivery_note.workers.leases import _claim_job
from tests.support.postgres import PostgreSQLCase


class DatabaseConcurrencyTests(PostgreSQLCase):
    def test_postgresql_partial_unique_index_allows_only_one_active_version(self):
        migrate_schema(self.database_url)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                user = User(username="admin", password_hash="test", role="admin")
                session.add(user)
                session.flush()
                session.add_all(
                    [
                        InputVersion(
                            kind="product",
                            name="inactive-1",
                            original_name="1.xlsx",
                            storage_path="/1.xlsx",
                            active=False,
                            created_by=user.id,
                        ),
                        InputVersion(
                            kind="product",
                            name="inactive-2",
                            original_name="2.xlsx",
                            storage_path="/2.xlsx",
                            active=False,
                            created_by=user.id,
                        ),
                        InputVersion(
                            kind="product",
                            name="active-1",
                            original_name="3.xlsx",
                            storage_path="/3.xlsx",
                            active=True,
                            created_by=user.id,
                        ),
                    ]
                )
                session.commit()
                session.add(
                    InputVersion(
                        kind="product",
                        name="active-2",
                        original_name="4.xlsx",
                        storage_path="/4.xlsx",
                        active=True,
                        created_by=user.id,
                    )
                )
                with self.assertRaises(IntegrityError):
                    session.commit()
        finally:
            database.dispose()

    def test_two_workers_claim_one_queued_job_exactly_once(self):
        migrate_schema(self.database_url)
        setup_database = Database(self.database_url)
        try:
            with setup_database.session() as session:
                _, batch, _ = self.create_batch(session, "claim-test")
                job = Job(batch_id=batch.id, kind="compute", status="queued")
                session.add(job)
                session.commit()
                job_id = job.id
        finally:
            setup_database.dispose()

        first_database = Database(self.database_url)
        second_database = Database(self.database_url)
        update_reached = Event()
        allow_commit = Event()

        def pause_first_update(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ):
            if statement.lstrip().upper().startswith("UPDATE JOBS"):
                update_reached.set()
                if not allow_commit.wait(timeout=10):
                    raise TimeoutError("等待第二个 Worker claim 超时")

        event.listen(
            first_database.engine,
            "before_cursor_execute",
            pause_first_update,
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                first_future = executor.submit(_claim_job, first_database)
                self.assertTrue(update_reached.wait(timeout=10))
                second_claim = _claim_job(second_database)
                allow_commit.set()
                first_claim = first_future.result(timeout=10)
        finally:
            allow_commit.set()
            first_database.dispose()
            second_database.dispose()

        self.assertIsNotNone(first_claim)
        self.assertEqual(first_claim[0], job_id)
        self.assertIsNone(second_claim)

        database = Database(self.database_url)
        try:
            with database.session() as session:
                job = session.get(Job, job_id)
                self.assertEqual(job.status, "running")
                self.assertEqual(job.attempts, 1)
                self.assertEqual(job.claim_token, first_claim[3])
        finally:
            database.dispose()
