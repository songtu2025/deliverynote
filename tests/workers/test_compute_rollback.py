from tests.support.worker import WorkerCase
from pathlib import Path

from sqlalchemy import select

from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
)

from delivery_note.worker import (
    run_once,
)


class WorkerIntegrationTests(WorkerCase):
    def test_self_operated_multi_file_compute_failure_persists_no_partial_result(self):
        created = self.client.post(
            "/api/self-operated-batches",
            headers=self.headers,
            json={"name": "自营仓多文件原子计算"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        source_paths = [
            self.create_self_operated_delivery(
                self.root / "260817-狂飙-原子-A.xlsx",
                5,
            ),
            self.create_self_operated_delivery(
                self.root / "260817-狂飙-原子-B.xlsx",
                5,
            ),
        ]
        for source_path in source_paths:
            with source_path.open("rb") as upload:
                response = self.client.post(
                    f"/api/batches/{batch_id}/files",
                    headers=self.headers,
                    files={"file": (source_path.name, upload)},
                )
            self.assertEqual(response.status_code, 201, response.text)
        inbound_path = self.create_self_operated_inbound(
            self.root / "自营仓原子计算待入库.xlsx"
        )
        with inbound_path.open("rb") as upload:
            response = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=self.headers,
                files={"file": (inbound_path.name, upload)},
            )
        self.assertEqual(response.status_code, 200, response.text)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=self.headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        compute = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=self.headers,
        )
        self.assertEqual(compute.status_code, 202, compute.text)

        with self.app.state.database.session() as session:
            sources = session.scalars(
                select(BatchFile)
                .where(BatchFile.batch_id == batch_id)
                .order_by(BatchFile.file_order)
            ).all()
            Path(sources[1].storage_path).write_bytes(b"invalid")

        with self.assertLogs("delivery_note.worker", level="ERROR"):
            self.assertEqual(
                run_once(self.database_url, self.storage_root),
                compute.json()["id"],
            )
        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            ).all()
            exceptions = session.scalars(
                select(ExceptionRecord)
                .join(BatchFile)
                .where(BatchFile.batch_id == batch_id)
            ).all()
            self.assertEqual(batch.status, "failed")
            self.assertEqual(
                [
                    (source.import_total, source.manual_total, source.import_rows)
                    for source in sources
                ],
                [(0, 0, []), (0, 0, [])],
            )
            self.assertEqual(exceptions, [])
