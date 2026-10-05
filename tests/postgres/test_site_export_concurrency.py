"""验证站点选择与导出在同一批次上互斥。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic

from sqlalchemy import event, select, text

from delivery_note.web.models import (
    Batch,
    ExceptionRecord,
    Job,
    SelfOperatedBatch,
    SelfOperatedSiteResolution,
)
from delivery_note.workers.leases import _claim_job
from tests.support.postgres import PostgreSQLCase


class SiteExportConcurrencyTests(PostgreSQLCase):
    def _seed_site_choice(self, app, batch_id, file_id):
        with app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            session.add(
                SelfOperatedBatch(
                    batch_id=batch_id,
                    template_version_id=batch.product_version_id,
                )
            )
            session.add(Job(batch_id=batch_id, kind="compute", status="succeeded"))
            record = ExceptionRecord(
                batch_file_id=file_id,
                sku="SKU-A",
                original_site="US",
                full_site="AMAZON:SEEKWAY:US、AMAZON:RIVMOUNT:US",
                delivery_quantity=1,
                allocated_quantity=0,
                manual_quantity=1,
                reason="产品信息站点不唯一",
                reason_code="ambiguous_product_site",
            )
            session.add(record)
            session.commit()
            return record.id

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
            rid = self._seed_site_choice(app, bid, files[0])
            database = app.state.database
            with (
                self._batch_waiter(database) as waiter,
                self.paused_sql(
                    database.engine, "INSERT INTO SELF_OPERATED_SITE_RESOLUTIONS"
                ) as (entered, resume),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    choice = executor.submit(
                        client.put,
                        f"/api/exceptions/{rid}/self-operated-site",
                        headers=headers,
                        json={"full_site": "AMAZON:SEEKWAY:US"},
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
                    self.assertEqual(choice.result(10).status_code, 202)
                    self.assertEqual(export.result(10).status_code, 409)
            with database.session() as session:
                self.assertEqual(session.get(Batch, bid).status, "queued")
                jobs = session.scalars(select(Job).where(Job.batch_id == bid)).all()
                self.assertEqual(
                    [(job.kind, job.status) for job in jobs], [("compute", "queued")]
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
            rid = self._seed_site_choice(app, bid, files[0])
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
                            client.put,
                            f"/api/exceptions/{rid}/self-operated-site",
                            headers=headers,
                            json={"full_site": "AMAZON:SEEKWAY:US"},
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
            self.assertIsNone(session.scalar(select(SelfOperatedSiteResolution)))
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
            rid = self._seed_site_choice(app, bid, files[0])
            export = client.post(f"/api/batches/{bid}/export", headers=headers)
            self.assertEqual(export.status_code, 202)
            for status in ("queued", "running"):
                with self.subTest(status=status):
                    if status == "running":
                        claim = _claim_job(app.state.database)
                        self.assertEqual(claim[0], export.json()["id"])
                    response = client.put(
                        f"/api/exceptions/{rid}/self-operated-site",
                        headers=headers,
                        json={"full_site": "AMAZON:SEEKWAY:US"},
                    )
                    self.assertEqual(response.status_code, 409)
                    self._assert_export_unchanged(app.state.database, bid, status)
