from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from delivery_note.migrations.runner import migrate_schema
import delivery_note.web.api as web_api_module
from delivery_note.web.api import create_app
from delivery_note.web.database import Database
from delivery_note.web.models import (
    Batch,
    BatchFile,
    BatchOverreceiptRule,
    ExceptionRecord,
    InputVersion,
    Job,
    OverreceiptRuleVersion,
    PurchaseSyncJob,
    User,
)
from delivery_note.worker import _claim_job
from tests.asgi_client import SyncASGIClient


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")


@unittest.skipUnless(
    POSTGRES_TEST_URL,
    "未设置 POSTGRES_TEST_URL，跳过 PostgreSQL 集成测试",
)
class PostgreSQLIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.schema = f"test_{uuid4().hex}"
        self.admin_engine = create_engine(POSTGRES_TEST_URL, future=True)
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        parsed_url = make_url(POSTGRES_TEST_URL)
        query = dict(parsed_url.query)
        query["options"] = f"-csearch_path={self.schema}"
        self.database_url = parsed_url.set(query=query).render_as_string(
            hide_password=False
        )

    def tearDown(self):
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin_engine.dispose()

    @contextmanager
    def batch_api(
        self, batch_status: str, file_count: int = 0, preflight_inputs: bool = False
    ):
        with TemporaryDirectory() as directory:
            app = create_app(
                database_url=self.database_url,
                storage_root=Path(directory) / "storage",
                bootstrap_admin=("admin", "admin-pass"),
            )
            client = SyncASGIClient(app)
            try:
                login = client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "admin-pass"},
                )
                self.assertEqual(login.status_code, 200, login.text)
                headers = {"Authorization": f"Bearer {login.json()['token']}"}
                with app.state.database.session() as session:
                    admin = session.query(User).filter_by(username="admin").one()
                    versions = {}
                    version_kinds = ("product", "supplier")
                    if preflight_inputs:
                        version_kinds += ("purchase", "position", "template")
                    for kind in version_kinds:
                        path = Path(directory) / f"{kind}.xlsx"
                        path.write_bytes(b"test")
                        version = InputVersion(
                            kind=kind,
                            name=f"{kind}-test",
                            original_name=f"{kind}.xlsx",
                            storage_path=str(path),
                            created_by=admin.id,
                        )
                        session.add(version)
                        versions[kind] = version
                    session.flush()
                    batch = Batch(
                        name="concurrency-test",
                        status=batch_status,
                        created_by=admin.id,
                        purchase_version_id=(
                            versions["purchase"].id if preflight_inputs else None
                        ),
                        product_version_id=versions["product"].id,
                        supplier_version_id=versions["supplier"].id,
                        position_version_id=(
                            versions["position"].id if preflight_inputs else None
                        ),
                        template_version_id=(
                            versions["template"].id if preflight_inputs else None
                        ),
                    )
                    session.add(batch)
                    session.flush()
                    file_ids = []
                    for index in range(file_count):
                        path = Path(directory) / f"file-{index}.xlsx"
                        path.write_bytes(b"test")
                        source = BatchFile(
                            batch_id=batch.id,
                            original_name=f"file-{index}.xlsx",
                            storage_path=str(path),
                            file_order=index + 1,
                        )
                        session.add(source)
                        session.flush()
                        file_ids.append(source.id)
                    batch_id = batch.id
                    session.commit()
                yield app, client, headers, batch_id, file_ids
            finally:
                client.close()
                app.state.database.dispose()

    @contextmanager
    def paused_sql(self, engine, prefix: str):
        reached = Event()
        resume = Event()

        def pause(
            _connection, _cursor, statement, _parameters, _context, _executemany
        ):
            if statement.lstrip().upper().startswith(prefix):
                reached.set()
                if not resume.wait(timeout=10):
                    raise TimeoutError(f"等待并发 SQL 超时：{prefix}")

        event.listen(engine, "before_cursor_execute", pause)
        try:
            yield reached, resume
        finally:
            resume.set()
            event.remove(engine, "before_cursor_execute", pause)

    def test_export_queue_blocks_concurrent_batch_delete(self):
        with self.batch_api("succeeded") as (app, client, headers, batch_id, _):
            with self.paused_sql(
                app.state.database.engine, "INSERT INTO JOBS"
            ) as (job_inserted, allow_insert):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    export = executor.submit(
                        client.post,
                        f"/api/batches/{batch_id}/export",
                        headers=headers,
                    )
                    self.assertTrue(job_inserted.wait(timeout=10))
                    deletion = executor.submit(
                        client.request,
                        "DELETE",
                        "/api/batches",
                        headers=headers,
                        json={"batch_ids": [batch_id]},
                    )
                    self.assertFalse(deletion.done())
                    allow_insert.set()
                    export_response = export.result(timeout=10)
                    delete_response = deletion.result(timeout=10)
            self.assertEqual(export_response.status_code, 202, export_response.text)
            self.assertEqual(delete_response.status_code, 409, delete_response.text)
            with app.state.database.session() as session:
                self.assertIsNotNone(session.get(Batch, batch_id))
                job = session.query(Job).filter_by(batch_id=batch_id).one()
                self.assertEqual(job.status, "queued")

    def test_compute_queue_blocks_concurrent_file_reorder(self):
        with self.batch_api("preflight_ready", file_count=2) as (
            app, client, headers, batch_id, file_ids
        ):
            with self.paused_sql(
                app.state.database.engine, "INSERT INTO JOBS"
            ) as (job_inserted, allow_insert):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    compute = executor.submit(
                        client.post,
                        f"/api/batches/{batch_id}/compute",
                        headers=headers,
                    )
                    self.assertTrue(job_inserted.wait(timeout=10))
                    reorder = executor.submit(
                        client.put,
                        f"/api/batches/{batch_id}/files/order",
                        headers=headers,
                        json={"file_ids": list(reversed(file_ids))},
                    )
                    self.assertFalse(reorder.done())
                    allow_insert.set()
                    compute_response = compute.result(timeout=10)
                    reorder_response = reorder.result(timeout=10)
            self.assertEqual(compute_response.status_code, 202, compute_response.text)
            self.assertEqual(reorder_response.status_code, 409, reorder_response.text)
            with app.state.database.session() as session:
                self.assertEqual(session.get(Batch, batch_id).status, "queued")
                sources = session.query(BatchFile).filter_by(batch_id=batch_id).all()
                self.assertEqual(
                    {source.id: source.file_order for source in sources},
                    dict(zip(file_ids, (1, 2))),
                )

    def test_batch_delete_blocks_concurrent_export_queue(self):
        with self.batch_api("succeeded") as (app, client, headers, batch_id, _):
            with self.paused_sql(
                app.state.database.engine, "DELETE FROM BATCHES"
            ) as (deleting, allow_delete):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    deletion = executor.submit(
                        client.request,
                        "DELETE",
                        "/api/batches",
                        headers=headers,
                        json={"batch_ids": [batch_id]},
                    )
                    self.assertTrue(deleting.wait(timeout=10))
                    export = executor.submit(
                        client.post,
                        f"/api/batches/{batch_id}/export",
                        headers=headers,
                    )
                    self.assertFalse(export.done())
                    allow_delete.set()
                    delete_response = deletion.result(timeout=10)
                    export_response = export.result(timeout=10)
            self.assertEqual(delete_response.status_code, 200, delete_response.text)
            self.assertEqual(export_response.status_code, 404, export_response.text)
            with app.state.database.session() as session:
                self.assertIsNone(session.get(Batch, batch_id))
                self.assertEqual(
                    session.query(Job).filter_by(batch_id=batch_id).count(), 0
                )

    def test_file_reorder_blocks_concurrent_compute_queue(self):
        with self.batch_api("preflight_ready", file_count=2) as (
            app, client, headers, batch_id, file_ids
        ):
            with self.paused_sql(
                app.state.database.engine, "UPDATE BATCH_FILES"
            ) as (reordering, allow_reorder):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    reorder = executor.submit(
                        client.put,
                        f"/api/batches/{batch_id}/files/order",
                        headers=headers,
                        json={"file_ids": list(reversed(file_ids))},
                    )
                    self.assertTrue(reordering.wait(timeout=10))
                    compute = executor.submit(
                        client.post,
                        f"/api/batches/{batch_id}/compute",
                        headers=headers,
                    )
                    self.assertFalse(compute.done())
                    allow_reorder.set()
                    reorder_response = reorder.result(timeout=10)
                    compute_response = compute.result(timeout=10)
            self.assertEqual(reorder_response.status_code, 200, reorder_response.text)
            self.assertEqual(compute_response.status_code, 409, compute_response.text)
            with app.state.database.session() as session:
                self.assertEqual(session.get(Batch, batch_id).status, "draft")
                self.assertEqual(
                    session.query(Job).filter_by(batch_id=batch_id).count(), 0
                )

    def test_preflight_detects_concurrent_file_reorder(self):
        with self.batch_api(
            "draft", file_count=2, preflight_inputs=True
        ) as (app, client, headers, batch_id, file_ids):
            reading = Event()
            resume = Event()

            def pause_delivery_read(_path):
                reading.set()
                if not resume.wait(timeout=10):
                    raise TimeoutError("等待文件重排超时")

            with (
                patch.object(web_api_module, "read_supplier_workbook", return_value=[]),
                patch.object(web_api_module, "read_product_workbook"),
                patch.object(web_api_module, "read_purchase_workbook"),
                patch.object(web_api_module, "read_position_workbook"),
                patch.object(web_api_module, "validate_template_workbook"),
                patch.object(web_api_module, "resolve_supplier"),
                patch.object(
                    web_api_module,
                    "read_delivery_workbook",
                    side_effect=pause_delivery_read,
                ),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    preflight = executor.submit(
                        client.post,
                        f"/api/batches/{batch_id}/preflight",
                        headers=headers,
                    )
                    try:
                        self.assertTrue(reading.wait(timeout=10))
                        reorder = executor.submit(
                            client.put,
                            f"/api/batches/{batch_id}/files/order",
                            headers=headers,
                            json={"file_ids": list(reversed(file_ids))},
                        )
                        reorder_response = reorder.result(timeout=10)
                    finally:
                        resume.set()
                    preflight_response = preflight.result(timeout=10)
            self.assertEqual(reorder_response.status_code, 200, reorder_response.text)
            self.assertEqual(
                preflight_response.status_code, 409, preflight_response.text
            )
            with app.state.database.session() as session:
                self.assertEqual(session.get(Batch, batch_id).status, "draft")

    def test_unified_migration_creates_fresh_schema_idempotently(self):
        migrate_schema(self.database_url)
        migrate_schema(self.database_url)

        database = Database(self.database_url)
        try:
            inspector = inspect(database.engine)
            tables = set(inspector.get_table_names())
            batch_columns = {
                column["name"]: column
                for column in inspector.get_columns(Batch.__tablename__)
            }
            purchase_sync_columns = {
                column["name"]: column
                for column in inspector.get_columns(PurchaseSyncJob.__tablename__)
            }
            exception_columns = {
                column["name"]
                for column in inspector.get_columns(ExceptionRecord.__tablename__)
            }
        finally:
            database.dispose()

        self.assertIn(OverreceiptRuleVersion.__tablename__, tables)
        self.assertIn(BatchOverreceiptRule.__tablename__, tables)
        self.assertTrue(batch_columns["purchase_version_id"]["nullable"])
        self.assertTrue(batch_columns["position_version_id"]["nullable"])
        self.assertTrue(batch_columns["template_version_id"]["nullable"])
        self.assertTrue(purchase_sync_columns["product_version_id"]["nullable"])
        self.assertTrue(purchase_sync_columns["supplier_version_id"]["nullable"])
        self.assertIn("purchase_allocated_quantity", exception_columns)
        self.assertIn("overreceipt_allocated_quantity", exception_columns)
        self.assertIn("overreceipt_remaining_quantity", exception_columns)

    def test_unified_migration_upgrades_legacy_schema_and_preserves_data(self):
        migrate_schema(self.database_url)
        database = Database(self.database_url)
        try:
            with database.session() as session:
                user = User(username="legacy", password_hash="test", role="admin")
                session.add(user)
                session.flush()
                versions = {}
                for kind in ("purchase", "product", "supplier", "position", "template"):
                    version = InputVersion(
                        kind=kind,
                        name=f"{kind}-legacy",
                        original_name=f"{kind}.xlsx",
                        storage_path=f"/{kind}.xlsx",
                        active=True,
                        created_by=user.id,
                    )
                    session.add(version)
                    session.flush()
                    versions[kind] = version.id
                batch = Batch(
                    name="legacy-batch",
                    created_by=user.id,
                    purchase_version_id=versions["purchase"],
                    product_version_id=versions["product"],
                    supplier_version_id=versions["supplier"],
                    position_version_id=versions["position"],
                    template_version_id=versions["template"],
                )
                sync_job = PurchaseSyncJob(
                    status="succeeded",
                    created_by=user.id,
                    product_version_id=versions["product"],
                    supplier_version_id=versions["supplier"],
                )
                session.add_all([batch, sync_job])
                session.commit()
                batch_id = batch.id
                sync_job_id = sync_job.id

            with database.engine.begin() as connection:
                connection.execute(text("DROP TABLE batch_overreceipt_rules"))
                connection.execute(text("DROP TABLE overreceipt_rule_versions"))
                for column in (
                    "purchase_allocated_quantity",
                    "overreceipt_allocated_quantity",
                    "overreceipt_remaining_quantity",
                ):
                    connection.execute(
                        text(f"ALTER TABLE exceptions DROP COLUMN {column}")
                    )
                for column in (
                    "purchase_version_id",
                    "position_version_id",
                    "template_version_id",
                ):
                    connection.execute(
                        text(f"ALTER TABLE batches ALTER COLUMN {column} SET NOT NULL")
                    )
                for column in ("product_version_id", "supplier_version_id"):
                    connection.execute(
                        text(
                            "ALTER TABLE purchase_sync_jobs "
                            f"ALTER COLUMN {column} SET NOT NULL"
                        )
                    )
        finally:
            database.dispose()

        migrate_schema(self.database_url)

        database = Database(self.database_url)
        try:
            inspector = inspect(database.engine)
            tables = set(inspector.get_table_names())
            batch_columns = {
                column["name"]: column
                for column in inspector.get_columns(Batch.__tablename__)
            }
            purchase_sync_columns = {
                column["name"]: column
                for column in inspector.get_columns(PurchaseSyncJob.__tablename__)
            }
            exception_columns = {
                column["name"]
                for column in inspector.get_columns(ExceptionRecord.__tablename__)
            }
            with database.session() as session:
                batch = session.get(Batch, batch_id)
                sync_job = session.get(PurchaseSyncJob, sync_job_id)
                self.assertEqual(batch.name, "legacy-batch")
                self.assertEqual(sync_job.status, "succeeded")
        finally:
            database.dispose()

        self.assertIn(OverreceiptRuleVersion.__tablename__, tables)
        self.assertIn(BatchOverreceiptRule.__tablename__, tables)
        for column in (
            "purchase_version_id",
            "position_version_id",
            "template_version_id",
        ):
            self.assertTrue(batch_columns[column]["nullable"])
        for column in ("product_version_id", "supplier_version_id"):
            self.assertTrue(purchase_sync_columns[column]["nullable"])
        self.assertTrue(
            {
                "purchase_allocated_quantity",
                "overreceipt_allocated_quantity",
                "overreceipt_remaining_quantity",
            }.issubset(exception_columns)
        )

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
                user = User(username="admin", password_hash="test", role="admin")
                session.add(user)
                session.flush()
                versions = {}
                for kind in ("purchase", "product", "supplier", "position", "template"):
                    version = InputVersion(
                        kind=kind,
                        name=kind,
                        original_name=f"{kind}.xlsx",
                        storage_path=f"/{kind}.xlsx",
                        active=True,
                        created_by=user.id,
                    )
                    session.add(version)
                    session.flush()
                    versions[kind] = version.id
                batch = Batch(
                    name="claim-test",
                    created_by=user.id,
                    purchase_version_id=versions["purchase"],
                    product_version_id=versions["product"],
                    supplier_version_id=versions["supplier"],
                    position_version_id=versions["position"],
                    template_version_id=versions["template"],
                )
                session.add(batch)
                session.flush()
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


if __name__ == "__main__":
    unittest.main()
