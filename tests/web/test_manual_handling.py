"""人工处理输入、重排门禁和审校数量使用相同口径。"""

from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from delivery_note.web.models import (
    Batch,
    BatchFile,
    ExceptionRecord,
    Job,
    SelfOperatedBatch,
)
from delivery_note.web.receipt_state import receipt_signature
from delivery_note.web.manual_handling import apply_offline_inputs
from tests.support.exception_transfers import ExceptionTransferCase


class ManualHandlingTests(ExceptionTransferCase):
    def test_new_write_routes_require_authentication(self):
        anonymous = type(self.client)(self.app)
        try:
            allowance = anonymous.put(
                f"/api/batches/{self.batch_id}/manual-allowances",
                json={
                    "supplier_code": "GYS-023",
                    "sku": "SKU-A",
                    "full_site": "AMAZON:SEEKWAY:US",
                    "quantity": 1,
                    "reason": "登记",
                },
            )
            offline = anonymous.put(
                f"/api/exceptions/{self.exception_id}/offline-handling",
                json={"quantity": 1, "note": "登记"},
            )
            self.assertEqual((allowance.status_code, offline.status_code), (401, 401))
        finally:
            anonymous.close()

    def test_concurrent_transfer_and_offline_never_exceed_manual_quantity(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            transfer = executor.submit(self.transfer, 5)
            offline = executor.submit(self.offline, 5)
            responses = [transfer.result(), offline.result()]
        self.assertEqual(
            sum(response.status_code in (200, 201) for response in responses), 1
        )
        record = self.records()[0]
        self.assertEqual(record["offline_quantity"] + record["transferred_quantity"], 5)

    def offline(self, quantity, note="线下登记"):
        return self.client.put(
            f"/api/exceptions/{self.exception_id}/offline-handling",
            headers=self.headers,
            json={"quantity": quantity, "note": note},
        )

    def allowance(self, quantity=3, **changes):
        return self.client.put(
            f"/api/batches/{self.batch_id}/manual-allowances",
            headers=self.headers,
            json={
                "supplier_code": "GYS-023",
                "sku": "SKU-A",
                "full_site": "AMAZON:SEEKWAY:US",
                "quantity": quantity,
                "reason": "补录实收",
                **changes,
            },
        )

    def snapshot(self):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            profile = session.get(SelfOperatedBatch, self.batch_id)
            sources = session.scalars(
                select(BatchFile).where(BatchFile.batch_id == batch.id)
            ).all()
            profile.receipt_snapshot = {
                "signature": receipt_signature(batch, profile, sources),
                "path": "synthetic",
                "summary": {"issue_count": 0},
            }
            for source in sources:
                source.receipt_context = {"issue_count": 0, "rows": [{"sku": "SKU-A"}]}
                source.result_path = "old.xlsx"
            session.add(Job(batch_id=batch.id, kind="compute", status="succeeded"))
            session.add(
                Job(
                    batch_id=batch.id,
                    kind="export",
                    status="succeeded",
                    output_path="old.xlsx",
                )
            )
            batch.zip_path = "old.zip"
            session.commit()
            return profile.receipt_snapshot, sources[0].receipt_context

    def test_offline_partial_all_replacement_and_revoke_preserve_conservation(self):
        self.assertEqual(self.offline(3).json()["status"], "pending")
        page = self.client.get(
            f"/api/batches/{self.batch_id}/exceptions?limit=10", headers=self.headers
        ).json()
        self.assertEqual(page["stats"]["unfinished_quantity"], 5)
        self.assertEqual(self.offline(8).json()["status"], "resolved")
        self.assertEqual(self.offline(4).json()["status"], "pending")
        summary = self.client.get(
            f"/api/batches/{self.batch_id}", headers=self.headers
        ).json()["summary"]
        self.assertEqual(
            summary,
            {
                "delivery_total": 20,
                "import_total": 12,
                "manual_total": 8,
                "conserved": True,
            },
        )
        record = self.records()[0]
        self.assertEqual(record["manual_quantity"], 8)
        self.assertEqual(record["offline_quantity"], 4)
        self.assertEqual(self.offline(0, "").json()["offline_note"], "")
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.get(SelfOperatedBatch, self.batch_id).manual_handling[
                    "offline"
                ],
                [],
            )

    def test_offline_validation_transfer_capacity_and_export_invalidation(self):
        for quantity, note in (
            (9, "原因"),
            (True, "原因"),
            (1.5, "原因"),
            (-1, "原因"),
            (1, " "),
        ):
            self.assertIn(self.offline(quantity, note).status_code, (400, 422))
        self.snapshot()
        self.assertEqual(self.offline(3).status_code, 200)
        self.assertEqual(self.transfer(6).status_code, 400)
        self.assertEqual(self.transfer(5).status_code, 201)
        self.assertEqual(self.offline(4).status_code, 400)
        self.assertEqual(self.records()[0]["status"], "resolved")
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            self.assertIsNone(batch.zip_path)
            export = session.scalar(
                select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
            )
            self.assertEqual(export.status, "stale")
            export.status = "running"
            session.commit()
        self.assertEqual(self.offline(0).status_code, 409)

    def test_allowance_requeues_only_compute_preserving_snapshot_and_receipt_context(
        self,
    ):
        snapshot, receipt = self.snapshot()
        self.offline(4)
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            result = self.allowance()
        self.assertEqual(result.status_code, 200, result.text)
        factory.assert_not_called()
        self.assertEqual(result.json()["status"], "queued")
        self.assertEqual(result.json()["manual_allowances"][0]["quantity"], 3)
        self.assertEqual(result.json()["jobs"]["compute"]["status"], "queued")
        self.assertEqual(result.json()["jobs"]["export"]["status"], "stale")
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.get(SelfOperatedBatch, self.batch_id).receipt_snapshot, snapshot
            )
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == self.batch_id)
            )
            self.assertEqual(source.receipt_context, receipt)
            self.assertEqual(source.import_rows, [])
            self.assertIsNone(session.get(ExceptionRecord, self.exception_id))
            self.assertEqual(
                session.get(SelfOperatedBatch, self.batch_id).manual_handling[
                    "offline"
                ][0]["quantity"],
                4,
            )
        self.assertEqual(self.allowance().status_code, 409)
        with self.app.state.database.session() as session:
            session.get(Batch, self.batch_id).status = "succeeded"
            session.scalar(
                select(Job).where(Job.batch_id == self.batch_id, Job.kind == "compute")
            ).status = "succeeded"
            session.commit()
        self.assertEqual(self.allowance(0).json()["manual_allowances"], [])

    def test_allowance_rejects_invalid_key_workflow_transfer_and_active_task(self):
        self.assertEqual(self.allowance(sku="不存在").status_code, 400)
        self.assertEqual(self.allowance(reason=" ").status_code, 422)
        with self.app.state.database.session() as session:
            job = Job(
                batch_id=self.batch_id, kind="purchase_snapshot", status="running"
            )
            session.add(job)
            session.commit()
        self.assertEqual(self.allowance().status_code, 409)
        with self.app.state.database.session() as session:
            session.scalar(
                select(Job).where(Job.batch_id == self.batch_id)
            ).status = "succeeded"
            session.commit()
        self.assertEqual(self.transfer(1).status_code, 201)
        self.assertIn("先处理超收再转交", self.allowance().text)
        with self.app.state.database.session() as session:
            session.delete(session.get(SelfOperatedBatch, self.batch_id))
            session.commit()
        self.assertEqual(self.allowance().status_code, 400)
        self.assertEqual(self.offline(1).status_code, 400)

    def test_reapply_offline_by_source_sku_site_caps_quantity_and_keeps_inputs(self):
        self.offline(6)
        with self.app.state.database.session() as session:
            entries = session.get(SelfOperatedBatch, self.batch_id).manual_handling[
                "offline"
            ]
            source_id = entries[0]["batch_file_id"]
            record = ExceptionRecord(
                batch_file_id=source_id,
                sku="SKU-A",
                full_site="AMAZON:SEEKWAY:US",
                manual_quantity=3,
            )
            apply_offline_inputs(record, entries)
            self.assertEqual((record.offline_quantity, record.status), (3, "resolved"))
            record.full_site = "OTHER"
            record.offline_quantity = 0
            apply_offline_inputs(record, entries)
            self.assertEqual(record.offline_quantity, 0)
            self.assertEqual(entries[0]["quantity"], 6)
