from tests.support.web_api import WebApiCase
from io import BytesIO

from sqlalchemy import select


from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    SplitRecord,
)


class WebApiTests(WebApiCase):
    def test_admin_can_delete_multiple_batches_and_owned_files(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        delivery = self.client.post(
            "/api/batches/with-files",
            headers=headers,
            data={"name": "delete-delivery-batch"},
            files={"files": ("delivery.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(delivery.status_code, 201, delivery.text)
        self_operated = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "delete-self-operated-batch"},
            files={
                "delivery_file": (
                    "quality-delivery.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "self-operated-inbound.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(self_operated.status_code, 201, self_operated.text)
        batch_ids = [delivery.json()["id"], self_operated.json()["id"]]
        batch_directories = [
            self.root / "storage" / "batches" / str(batch_id) for batch_id in batch_ids
        ]
        self.assertTrue(all(path.is_dir() for path in batch_directories))

        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == batch_ids[0])
            )
            exception = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-A",
                delivery_quantity=1,
                allocated_quantity=0,
                manual_quantity=1,
                reason="delete-test",
            )
            session.add(exception)
            session.flush()
            session.add(SplitRecord(exception_id=exception.id, quantity=1))
            session.add(
                Job(
                    batch_id=batch_ids[0],
                    kind="compute",
                    status="succeeded",
                )
            )
            session.commit()

        deleted = self.client.request(
            "DELETE",
            "/api/batches",
            headers=headers,
            json={"batch_ids": batch_ids},
        )

        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["deleted_ids"], batch_ids)
        self.assertEqual(deleted.json()["file_cleanup_failed_ids"], [])
        self.assertTrue(all(not path.exists() for path in batch_directories))
        self.assertEqual(
            self.client.get("/api/batches", headers=headers).json(),
            [],
        )

    def test_batch_delete_is_admin_only_and_rejects_active_batch_atomically(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        first = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "keep-batch"},
        ).json()
        active = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "running-batch"},
        ).json()
        with self.app.state.database.session() as session:
            session.get(Batch, active["id"]).status = "running"
            session.commit()

        operator = self.create_operator(admin_headers)
        operator_headers = self.login(operator["username"], "operator-pass")
        forbidden = self.client.request(
            "DELETE",
            "/api/batches",
            headers=operator_headers,
            json={"batch_ids": [first["id"]]},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

        blocked = self.client.request(
            "DELETE",
            "/api/batches",
            headers=admin_headers,
            json={"batch_ids": [first["id"], active["id"]]},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("running-batch", blocked.json()["detail"])
        remaining_ids = [
            batch["id"]
            for batch in self.client.get(
                "/api/batches",
                headers=admin_headers,
            ).json()
        ]
        self.assertEqual(set(remaining_ids), {first["id"], active["id"]})

    def test_batch_delete_rejects_active_export_job_atomically(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        first = self.client.post(
            "/api/batches", headers=headers, json={"name": "keep-batch"}
        ).json()
        exporting = self.client.post(
            "/api/batches", headers=headers, json={"name": "exporting-batch"}
        ).json()
        with self.app.state.database.session() as session:
            session.get(Batch, exporting["id"]).status = "succeeded"
            session.add(Job(batch_id=exporting["id"], kind="export", status="queued"))
            session.commit()

        for job_status in ("queued", "running"):
            with self.app.state.database.session() as session:
                job = session.scalar(select(Job).where(Job.batch_id == exporting["id"]))
                job.status = job_status
                session.commit()
            blocked = self.client.request(
                "DELETE",
                "/api/batches",
                headers=headers,
                json={"batch_ids": [first["id"], exporting["id"]]},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(
                {
                    batch["id"]
                    for batch in self.client.get("/api/batches", headers=headers).json()
                },
                {first["id"], exporting["id"]},
            )

        with self.app.state.database.session() as session:
            job = session.scalar(select(Job).where(Job.batch_id == exporting["id"]))
            job.status = "succeeded"
            session.commit()
        deleted = self.client.request(
            "DELETE",
            "/api/batches",
            headers=headers,
            json={"batch_ids": [first["id"], exporting["id"]]},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
