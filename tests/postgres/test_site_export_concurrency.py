"""验证重新取数与导出在同一批次上互斥。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic

from sqlalchemy import event, select, text

from delivery_note.web.models import (
    Batch,
    BatchFile,
    Job,
    SelfOperatedBatch,
)
from delivery_note.web.receipt_state import receipt_signature
from delivery_note.workers.leases import _claim_job
from tests.support.postgres import PostgreSQLCase


class SiteExportConcurrencyTests(PostgreSQLCase):
    def _seed_site_choice(self, app, batch_id, file_id):
        with app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            profile = SelfOperatedBatch(
                batch_id=batch_id, template_version_id=batch.product_version_id
            )
            session.add(profile)
            source = session.get(BatchFile, file_id)
            source.receipt_context = {"issue_count": 0, "requested_total": 1}
            session.flush()
            profile.receipt_snapshot = {
                "signature": receipt_signature(batch, profile, [source])
            }
            session.add(Job(batch_id=batch_id, kind="compute", status="succeeded"))
            session.commit()
            return file_id

    @contextmanager
    def _batch_waiter(self, database):
        reached = Event()
        backend_pids = []

        def observe(connection, _cursor, statement, _parameters, _context, _many):
            if "FROM batches" in statement and "FOR UPDATE" in statement:
                backend_pids.append(
                    connection.connection.driver_connection.info.backend_pid
                )
                reached.set()

        event.listen(database.engine, "before_cursor_execute", observe)
        try:
            yield reached, backend_pids
        finally:
            event.remove(database.engine, "before_cursor_execute", observe)

    def _assert_blocked(self, database, future, waiter):
        reached, pids = waiter
        self.assertTrue(reached.wait(10))
        deadline = monotonic() + 10
        while monotonic() < deadline and not future.done():
            with database.engine.connect() as connection:
                blockers = connection.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))"),
                    {"pid": pids[-1]},
                )
            if blockers:
                return
            Event().wait(0.01)
        self.fail("并发请求未等待批次行锁")

    def test_site_choice_blocks_concurrent_export(self):
        with self.batch_api("succeeded", file_count=1) as (
            app,
            client,
            headers,
            bid,
            files,
        ):
            self._seed_site_choice(app, bid, files[0])
            database = app.state.database
            with (
                self._batch_waiter(database) as waiter,
                self.paused_sql(database.engine, "UPDATE SELF_OPERATED_BATCHES") as (
                    entered,
                    resume,
                ),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    choice = executor.submit(
                        client.post,
                        f"/api/batches/{bid}/receipts/refresh",
                        headers=headers,
                    )
                    try:
                        self.assertTrue(entered.wait(10))
                        waiter[0].clear()
                        waiter[1].clear()
                        export = executor.submit(
                            client.post,
                            f"/api/batches/{bid}/export",
                            headers=headers,
                        )
                        self._assert_blocked(database, export, waiter)
                    finally:
                        resume.set()
                    self.assertEqual(choice.result(10).status_code, 200)
                    self.assertEqual(export.result(10).status_code, 409)
            with database.session() as session:
                self.assertEqual(session.get(Batch, bid).status, "queued")
                jobs = session.scalars(select(Job).where(Job.batch_id == bid)).all()
                self.assertEqual(
                    [(job.kind, job.status) for job in jobs],
                    [("compute", "stale"), ("prepare", "queued")],
                )
                self.assertIsNone(session.get(Batch, bid).zip_path)

    def test_export_blocks_concurrent_site_choice(self):
        with self.batch_api("succeeded", file_count=1) as (
            app,
            client,
            headers,
            bid,
            files,
        ):
            self._seed_site_choice(app, bid, files[0])
            database = app.state.database
            with (
                self._batch_waiter(database) as waiter,
                self.paused_sql(database.engine, "INSERT INTO JOBS") as (
                    entered,
                    resume,
                ),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    export = executor.submit(
                        client.post, f"/api/batches/{bid}/export", headers=headers
                    )
                    try:
                        self.assertTrue(entered.wait(10))
                        waiter[0].clear()
                        waiter[1].clear()
                        choice = executor.submit(
                            client.post,
                            f"/api/batches/{bid}/receipts/refresh",
                            headers=headers,
                        )
                        self._assert_blocked(database, choice, waiter)
                    finally:
                        resume.set()
                    self.assertEqual(export.result(10).status_code, 202)
                    self.assertEqual(choice.result(10).status_code, 409)
            self._assert_export_unchanged(database, bid, "queued")

    def _assert_export_unchanged(self, database, batch_id, expected_status):
        with database.session() as session:
            self.assertEqual(session.get(Batch, batch_id).status, "succeeded")
            self.assertIsNotNone(
                session.get(SelfOperatedBatch, batch_id).receipt_snapshot
            )
            job = session.scalar(
                select(Job).where(Job.batch_id == batch_id, Job.kind == "export")
            )
            self.assertEqual(job.status, expected_status)

    def test_queued_and_running_export_reject_site_choice(self):
        with self.batch_api("succeeded", file_count=1) as (
            app,
            client,
            headers,
            bid,
            files,
        ):
            self._seed_site_choice(app, bid, files[0])
            export = client.post(f"/api/batches/{bid}/export", headers=headers)
            self.assertEqual(export.status_code, 202)
            for status in ("queued", "running"):
                with self.subTest(status=status):
                    if status == "running":
                        claim = _claim_job(app.state.database)
                        self.assertEqual(claim[0], export.json()["id"])
                    response = client.post(
                        f"/api/batches/{bid}/receipts/refresh",
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 409)
                    self._assert_export_unchanged(app.state.database, bid, status)
