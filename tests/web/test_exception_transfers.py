from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import func, select
from openpyxl import load_workbook

from delivery_note.excel_io import read_delivery_workbook
from delivery_note.web.models import Batch, BatchFile, Job, InputVersion
from delivery_note.web.models.batches import ExceptionTransfer
from delivery_note.worker import run_once
from tests.support.exception_transfers import ExceptionTransferCase


class ExceptionTransferTests(ExceptionTransferCase):
    def test_partial_then_full_transfer_preserves_summary_and_history(self):
        first = self.transfer(3)
        self.assertEqual(first.status_code, 201, first.text)
        record = self.records()[0]
        self.assertEqual(record["manual_quantity"], 8)
        self.assertEqual(record["transferred_quantity"], 3)
        self.assertEqual(record["status"], "pending")
        second = self.transfer(5)
        self.assertEqual(second.status_code, 201, second.text)
        record = self.records()[0]
        self.assertEqual(record["status"], "resolved")
        self.assertEqual(record["transferred_quantity"], 8)
        self.assertEqual(len(record["transfers"]), 2)
        detail = self.client.get(
            f"/api/batches/{self.batch_id}", headers=self.headers
        ).json()
        self.assertEqual(detail["summary"]["manual_total"], 8)
        self.assertEqual(detail["summary"]["import_total"], 12)
        pending = self.client.get(
            f"/api/batches/{self.batch_id}/exceptions?review_scope=unfinished",
            headers=self.headers,
        ).json()
        self.assertEqual(pending, [])
        self.assertNotIn("export", detail["jobs"])
        self.assertEqual(self.transfer().status_code, 400)

    def test_invalid_quantities_sites_and_duplicate_items_leave_no_results(self):
        for quantity in (0, -1, 9, 1.5, True, "2"):
            with self.subTest(quantity=quantity):
                self.assertIn(self.transfer(quantity).status_code, (400, 422))
        self.assertEqual(self.transfer(full_site="AMAZON:OTHER:US").status_code, 400)
        self.assertEqual(self.transfer(exception_id=999999).status_code, 400)
        response = self.client.post(
            f"/api/batches/{self.batch_id}/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={
                "items": [
                    {
                        "exception_id": self.exception_id,
                        "quantity": 5,
                        "full_site": "AMAZON:SEEKWAY:US",
                    }
                ]
                * 2
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.records()[0]["transferred_quantity"], 0)

    def test_repeated_partial_submission_cannot_exceed_remaining(self):
        self.assertEqual(self.transfer(5).status_code, 201)
        self.assertEqual(self.transfer(5).status_code, 400)
        self.assertEqual(self.records()[0]["transferred_quantity"], 5)

    def test_batch_state_export_and_resolved_guards(self):
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "draft"
            session.commit()
        self.assertEqual(self.transfer().status_code, 409)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.status = "succeeded"
            session.add(Job(batch_id=batch.id, kind="export", status="running"))
            session.commit()
        self.assertEqual(self.transfer().status_code, 409)

    def test_generated_workbook_and_current_versions_are_bound(self):
        response = self.transfer()
        self.assertEqual(response.status_code, 201, response.text)
        target_id = response.json()["id"]
        with self.app.state.database.session() as session:
            batch = session.get(Batch, target_id)
            self.assertEqual(batch.purchase_version_id, self.versions["purchase"])
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == target_id)
            )
            self.assertEqual(source.receipt_sites, {"SKU-A	US": "AMAZON:SEEKWAY:US"})
            rows = read_delivery_workbook(Path(source.storage_path))
            self.assertEqual(rows["交货量"].tolist(), [8])
            self.assertEqual(rows["原始站点"].tolist(), ["US"])

    def test_options_cache_reads_product_once_and_keeps_purchase_error(self):
        from delivery_note.excel_io import read_product_workbook

        path = f"/api/exceptions/{self.exception_id}/transfer-options"
        with patch(
            "delivery_note.web.exception_transfer_files.read_product_workbook",
            wraps=read_product_workbook,
        ) as reader:
            for _ in range(2):
                response = self.client.get(path, headers=self.headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["sites"], ["AMAZON:SEEKWAY:US"])
                self.assertEqual(response.json()["purchases"], [])
                self.assertIn("采购数据", response.json()["purchase_error"])
            reader.assert_called_once()

    def test_options_missing_supplier_still_returns_sites(self):
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == self.batch_id)
            )
            source.supplier_code = ""
            session.commit()
        response = self.client.get(
            f"/api/exceptions/{self.exception_id}/transfer-options",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["sites"])
        self.assertIn("供应商编码", response.json()["purchase_error"])

    def test_supplier_filename_mismatch_rejected(self):
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == self.batch_id)
            )
            source.supplier_code = "MISSING"
            session.commit()
        response = self.transfer()
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("供应商", response.json()["detail"])

    def test_concurrent_requests_do_not_overtransfer(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.transfer(5), range(2)))
        self.assertEqual(
            sorted(response.status_code for response in responses), [201, 400]
        )
        self.assertEqual(self.records()[0]["transferred_quantity"], 5)

    def test_other_batch_and_unauthenticated_requests_are_rejected(self):
        other = self.client.post(
            "/api/batches", headers=self.headers, json={"name": "交货"}
        ).json()
        response = self.client.post(
            f"/api/batches/{other['id']}/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={
                "items": [
                    {
                        "exception_id": self.exception_id,
                        "quantity": 1,
                        "full_site": "AMAZON:SEEKWAY:US",
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.get(
            f"/api/exceptions/{self.exception_id}/transfer-options"
        )
        self.assertEqual(response.status_code, 401)

    def test_site_change_reaches_worker_even_when_original_site_is_locked(self):
        with self.app.state.database.session() as session:
            versions = {kind: self.versions[kind] for kind in ("product", "purchase")}
            for kind, version_id in versions.items():
                version = session.get(InputVersion, version_id)
                workbook = load_workbook(version.storage_path)
                if kind == "product":
                    workbook.active.append(["SKU-A", "OTHER:US", "水鞋", ""])
                else:
                    workbook.active.append(
                        [
                            "待交货",
                            "KuangBiao",
                            "SKU-A",
                            "AMAZON:OTHER:US",
                            "水鞋-广州仓",
                            30,
                        ]
                    )
                workbook.save(version.storage_path)
                workbook.close()
        response = self.transfer(full_site="AMAZON:OTHER:US")
        self.assertEqual(response.status_code, 201, response.text)
        target = response.json()["id"]
        with self.app.state.database.session() as session:
            source_export = session.scalar(
                select(Job).where(Job.batch_id == self.batch_id, Job.kind == "export")
            )
            self.assertIsNone(source_export)
        preflight = self.client.post(
            f"/api/batches/{target}/preflight", headers=self.headers
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        job = self.client.post(f"/api/batches/{target}/compute", headers=self.headers)
        database_url = str(self.app.state.database.engine.url)
        self.assertEqual(
            run_once(database_url, self.root / "storage"), job.json()["id"]
        )
        with self.app.state.database.session() as session:
            self.assertEqual(session.get(Batch, target).status, "succeeded")
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == target)
            )
            self.assertEqual(source.import_rows[0]["*站点"], "AMAZON:OTHER:US")
            self.assertEqual(
                source.import_rows[0]["单据备注"], "261008-KuangBiao-01-194箱"
            )
            self.assertEqual(source.import_total, 8)
        exported = self.client.post(
            f"/api/batches/{target}/export", headers=self.headers
        )
        self.assertEqual(exported.status_code, 202, exported.text)
        self.assertEqual(
            run_once(database_url, self.root / "storage"), exported.json()["id"]
        )
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == target)
            )
            self.assertTrue(Path(source.result_path).is_file())
            self.assertEqual(source.receipt_sites, {"SKU-A\tUS": "AMAZON:OTHER:US"})

    def test_same_short_site_different_full_sites_are_rejected(self):
        second = self.add_source(order=2)
        with self.app.state.database.session() as session:
            from delivery_note.web.models import ExceptionRecord

            session.get(ExceptionRecord, second).batch_file_id = session.get(
                ExceptionRecord, self.exception_id
            ).batch_file_id
            version = session.get(InputVersion, self.versions["product"])
            workbook = load_workbook(version.storage_path)
            workbook.active.append(["SKU-A", "OTHER:US", "水鞋", ""])
            workbook.save(version.storage_path)
            workbook.close()
            session.commit()
        response = self.client.post(
            f"/api/batches/{self.batch_id}/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={
                "items": [
                    {
                        "exception_id": self.exception_id,
                        "quantity": 3,
                        "full_site": "AMAZON:SEEKWAY:US",
                    },
                    {
                        "exception_id": second,
                        "quantity": 3,
                        "full_site": "AMAZON:OTHER:US",
                    },
                ]
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("多个完整站点", response.json()["detail"])
        self.assertEqual(self.records()[0]["transferred_quantity"], 0)

    def test_partial_pending_stats_subtract_transferred_quantity(self):
        self.assertEqual(self.transfer(3).status_code, 201)
        page = self.client.get(
            f"/api/batches/{self.batch_id}/exceptions?limit=10", headers=self.headers
        ).json()
        self.assertEqual(page["stats"]["unfinished_quantity"], 5)
        self.assertEqual(page["stats"]["unfinished_count"], 1)

    def test_failure_after_files_created_rolls_back_everything(self):
        with patch(
            "delivery_note.web.exception_transfers.ExceptionTransfer",
            side_effect=RuntimeError("合成故障"),
        ):
            with self.assertRaisesRegex(RuntimeError, "合成故障"):
                self.transfer()
        with self.app.state.database.session() as session:
            self.assertEqual(session.scalar(select(func.count(Batch.id))), 1)
            self.assertEqual(session.scalar(select(func.count(BatchFile.id))), 1)
            self.assertEqual(
                session.scalar(select(func.count(ExceptionTransfer.id))), 0
            )
        self.assertFalse(list((self.root / "storage" / "batches").rglob("*.xlsx")))
        self.assertEqual(self.records()[0]["status"], "pending")
