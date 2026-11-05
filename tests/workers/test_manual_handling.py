"""人工输入经过真实计算与导出，重算不重新访问历史。"""

from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook
from sqlalchemy import select

from delivery_note.web.models import BatchFile, SelfOperatedBatch
from delivery_note.worker import run_once
from tests.support.receipt_worker import ReceiptWorkerCase
from tests.support.inbound_inputs import create_ambiguous_product
from tests.inbound.test_history import inbound_order
from tests.support.inbound_exports import assert_inbound_progress


class ManualHandlingWorkerTests(ReceiptWorkerCase):
    def test_offline_and_transfer_refresh_all_download_formats(self):
        batch_id = self.create_receipt_batch(cumulative=50)
        delivery = self.create_self_operated_delivery(
            self.root / "狂飙-第二份.xlsx", 20, "LN2608170002"
        )
        with self.app.state.database.session() as session:
            inbound_path = session.get(SelfOperatedBatch, batch_id).inbound_storage_path
        workbook = load_workbook(inbound_path)
        sheet = workbook.worksheets[0]
        columns = [cell.value for cell in sheet[1]]
        for original in list(sheet.iter_rows(min_row=2, values_only=True)):
            values = list(original)
            values[columns.index("关联交货单/调拨单")] = "LN2608170002"
            values[columns.index("积加明细ID")] += "-2"
            sheet.append(values)
        workbook.save(inbound_path)
        workbook.close()
        path = f"/api/batches/{batch_id}"
        with delivery.open("rb") as upload:
            result = self.client.post(
                path + "/files",
                headers=self.headers,
                files={"file": (delivery.name, upload)},
            )
        self.assertEqual(result.status_code, 201, result.text)
        self.preflight(batch_id)
        run_once(self.database_url, self.storage_root)
        run_once(self.database_url, self.storage_root)
        before = self.client.get(path, headers=self.headers).json()
        downloads = [path + "/download", path + "/download-merged"] + [
            f"/api/batch-files/{source['id']}/download" for source in before["files"]
        ]
        original = []
        for download in downloads:
            result = self.client.get(download, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            original.append(result.content)
        pending = self.client.get(path + "/exceptions", headers=self.headers).json()[0]
        source_name = next(
            source["original_name"]
            for source in before["files"]
            if source["id"] == pending["batch_file_id"]
        )
        saved = self.client.put(
            f"/api/exceptions/{pending['id']}/offline-handling",
            headers=self.headers,
            json={"quantity": 1},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        for download in downloads:
            self.assertEqual(
                self.client.get(download, headers=self.headers).status_code, 404
            )
        queued = self.client.get(path, headers=self.headers).json()
        self.assertEqual(queued["jobs"]["export"]["status"], "queued")
        run_once(self.database_url, self.storage_root)
        transferred = self.client.post(
            path + "/exceptions/transfer-to-delivery",
            headers=self.headers,
            json={
                "items": [
                    {
                        "exception_id": pending["id"],
                        "quantity": pending["manual_quantity"] - 1,
                        "full_site": pending["full_site"],
                    }
                ]
            },
        )
        self.assertEqual(transferred.status_code, 201, transferred.text)
        after = self.client.get(path, headers=self.headers).json()
        self.assertEqual(after["jobs"]["export"]["id"], before["jobs"]["export"]["id"])
        self.assertEqual(after["jobs"]["export"]["status"], "queued")
        self.assertTrue(after["summary"]["conserved"])
        run_once(self.database_url, self.storage_root)
        for download, content in zip(downloads, original):
            result = self.client.get(download, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            if download == path + "/download":
                with (
                    ZipFile(BytesIO(content)) as old,
                    ZipFile(BytesIO(result.content)) as new,
                ):
                    for name in old.namelist():
                        assert_inbound_progress(
                            self, old.read(name), new.read(name), pending, source_name
                        )
            else:
                assert_inbound_progress(
                    self, content, result.content, pending, source_name
                )

    def test_site_adjustment_reuses_history_and_automatically_computes_and_exports(
        self,
    ):
        product = create_ambiguous_product(self.root / "ambiguous.xlsx")
        with product.open("rb") as upload:
            response = self.client.post(
                "/api/input-versions/product",
                headers=self.headers,
                data={"name": "站点候选", "activate": "true"},
                files={"file": (product.name, upload)},
            )
        self.assertEqual(response.status_code, 201, response.text)
        batch_id = self.create_receipt_batch(cumulative=50, managed=True)
        order = inbound_order()
        order.update(supplierName="KuangBiao", releatedCode="LN2608179025")
        other = inbound_order()
        other.update(
            id="order-2",
            orderNo="WV-2",
            supplierName="KuangBiao",
            releatedCode="LN2608179025",
        )
        other["orderItemResultList"][0].update(id="item-2", marketName="RIVMOUNT:US")
        other["onShelfOrderList"][0]["onShelfItemList"][0]["inboundItemId"] = "item-2"
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as initial:
            initial.return_value.list_self_operated_inbound_orders.return_value = [
                order,
                other,
            ]
            self.preflight(batch_id)
            initial.return_value.list_self_operated_inbound_orders.assert_called_once()
        run_once(self.database_url, self.storage_root)
        run_once(self.database_url, self.storage_root)
        path = f"/api/batches/{batch_id}"
        before = self.client.get(path, headers=self.headers).json()
        row = self.client.get(path + "/receipts", headers=self.headers).json()["items"][
            0
        ]
        with self.app.state.database.session() as session:
            snapshot = session.get(SelfOperatedBatch, batch_id).receipt_snapshot
        with (
            patch("delivery_note.workers.prepare_inbound._capture_snapshot") as capture,
            patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory,
        ):
            selected = self.client.put(
                path + "/adjustments",
                headers=self.headers,
                json={
                    "sites": [
                        {
                            "file_id": row["file_id"],
                            "sku": row["sku"],
                            "original_site": row["original_site"],
                            "full_site": "AMAZON:SEEKWAY:US",
                        }
                    ],
                },
            )
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertEqual(selected.json()["jobs"]["prepare"]["status"], "queued")
            run_once(self.database_url, self.storage_root)
            prepared = self.client.get(path, headers=self.headers).json()
            self.assertEqual(prepared["jobs"]["compute"]["status"], "queued")
            run_once(self.database_url, self.storage_root)
        capture.assert_not_called()
        factory.assert_not_called()
        after = self.client.get(path, headers=self.headers).json()
        self.assertEqual(after["jobs"]["export"]["status"], "queued")
        self.assertGreater(after["summary"]["manual_total"], 0)
        self.assertTrue(after["summary"]["conserved"])
        self.assertEqual(
            after["receipt"]["captured_at"], before["receipt"]["captured_at"]
        )
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.get(SelfOperatedBatch, batch_id).receipt_snapshot["signature"],
                snapshot["signature"],
            )
        run_once(self.database_url, self.storage_root)
        self.assertEqual(
            self.client.get(path + "/download", headers=self.headers).status_code, 200
        )

    def test_recompute_keeps_history_applies_offline_and_exports_annotations(self):
        batch_id = self.create_receipt_batch(cumulative=50)
        self.preflight(batch_id)
        response = self.client.post(
            f"/api/batches/{batch_id}/compute", headers=self.headers
        )
        self.assertEqual(response.status_code, 202)
        run_once(self.database_url, self.storage_root)
        path = f"/api/batches/{batch_id}"
        before = self.client.get(path, headers=self.headers).json()
        pending = self.client.get(path + "/exceptions", headers=self.headers).json()[0]
        self.assertGreater(pending["manual_quantity"], 5)
        self.assertEqual(before["jobs"]["export"]["status"], "queued")
        run_once(self.database_url, self.storage_root)
        exported = self.client.get(path + "/download", headers=self.headers)
        self.assertEqual(exported.status_code, 200, exported.text)
        saved = self.client.put(
            f"/api/exceptions/{pending['id']}/offline-handling",
            headers=self.headers,
            json={"quantity": pending["manual_quantity"], "note": "线下登记"},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        handled = self.client.get(path, headers=self.headers).json()
        self.assertEqual(handled["jobs"]["export"]["status"], "queued")
        self.assertEqual(
            self.client.get(path + "/download", headers=self.headers).status_code, 404
        )
        run_once(self.database_url, self.storage_root)
        with self.app.state.database.session() as session:
            snapshot = session.get(SelfOperatedBatch, batch_id).receipt_snapshot
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            )
            receipt = source.receipt_context
            supplier = source.supplier_code
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            result = self.client.put(
                path + "/manual-allowances",
                headers=self.headers,
                json={
                    "supplier_code": supplier,
                    "sku": pending["sku"],
                    "full_site": pending["full_site"],
                    "quantity": 3,
                    "reason": "确认实收",
                },
            )
            self.assertEqual(result.status_code, 200, result.text)
            run_once(self.database_url, self.storage_root)
        factory.assert_not_called()
        after = self.client.get(path, headers=self.headers).json()
        self.assertEqual(after["status"], "succeeded", after)
        self.assertEqual(after["version_ids"], before["version_ids"])
        self.assertEqual(
            after["self_operated_overreceipt_rule"],
            before["self_operated_overreceipt_rule"],
        )
        self.assertEqual(
            after["summary"]["import_total"], before["summary"]["import_total"] + 3
        )
        self.assertTrue(after["summary"]["conserved"])
        recomputed = self.client.get(path + "/exceptions", headers=self.headers).json()[
            0
        ]
        self.assertEqual(recomputed["offline_quantity"], pending["manual_quantity"] - 3)
        self.assertEqual(recomputed["status"], "resolved")
        self.assertEqual(after["jobs"]["export"]["status"], "queued")
        with self.app.state.database.session() as session:
            profile = session.get(SelfOperatedBatch, batch_id)
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            )
            self.assertEqual(profile.receipt_snapshot, snapshot)
            self.assertEqual(source.receipt_context, receipt)
            self.assertEqual(
                profile.manual_handling["offline"][0]["quantity"],
                pending["manual_quantity"],
            )
            self.assertIn(
                "人工追加超收：3；确认实收", source.import_rows[-1]["超收原因"]
            )
        self.client.post(path + "/export", headers=self.headers)
        run_once(self.database_url, self.storage_root)
        result = self.client.get(path + "/download", headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        book = load_workbook(BytesIO(result.content), data_only=True)
        self.assertEqual(book.sheetnames, ["批量入库", "待处理明细"])
        pending_sheet = book["待处理明细"]
        self.assertEqual(
            pending_sheet.cell(2, 13).value, pending["manual_quantity"] - 3
        )
        self.assertEqual(pending_sheet.cell(2, 14).value, "线下登记")
        self.assertEqual(pending_sheet.cell(2, 15).value, 0)
        book.close()
