from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch


import delivery_note.web.batch_preflight as preflight_module
from delivery_note.web.models import (
    Batch,
    BatchFile,
    Job,
)
from tests.support.postgres import PostgreSQLCase


class BatchConcurrencyTests(PostgreSQLCase):
    def test_export_queue_blocks_concurrent_batch_delete(self):
        with self.batch_api("succeeded") as (app, client, headers, batch_id, _):
            with self.paused_sql(app.state.database.engine, "INSERT INTO JOBS") as (
                job_inserted,
                allow_insert,
            ):
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
            app,
            client,
            headers,
            batch_id,
            file_ids,
        ):
            with self.paused_sql(app.state.database.engine, "INSERT INTO JOBS") as (
                job_inserted,
                allow_insert,
            ):
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
            with self.paused_sql(app.state.database.engine, "DELETE FROM BATCHES") as (
                deleting,
                allow_delete,
            ):
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
            app,
            client,
            headers,
            batch_id,
            file_ids,
        ):
            with self.paused_sql(app.state.database.engine, "UPDATE BATCH_FILES") as (
                reordering,
                allow_reorder,
            ):
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
        with self.batch_api("draft", file_count=2, preflight_inputs=True) as (
            app,
            client,
            headers,
            batch_id,
            file_ids,
        ):
            reading = Event()
            resume = Event()

            def pause_delivery_read(_path):
                reading.set()
                if not resume.wait(timeout=10):
                    raise TimeoutError("等待文件重排超时")

            with (
                patch.object(
                    preflight_module, "read_supplier_workbook", return_value=[]
                ),
                patch.object(preflight_module, "read_product_workbook"),
                patch.object(preflight_module, "read_purchase_workbook"),
                patch.object(preflight_module, "read_position_workbook"),
                patch.object(preflight_module, "validate_template_workbook"),
                patch.object(preflight_module, "resolve_supplier"),
                patch.object(
                    preflight_module,
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
