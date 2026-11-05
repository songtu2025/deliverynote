from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook

from delivery_note.web.models import BatchFile, SelfOperatedBatch
from delivery_note.worker import run_once
from tests.support.receipt_worker import ReceiptWorkerCase


class TargetedAllowanceWorkerTests(ReceiptWorkerCase):
    def add_second_file(self, batch_id):
        delivery = self.create_self_operated_delivery(
            self.root / "狂飙-第二份.xlsx", 5, "LN2608179026"
        )
        with self.app.state.database.session() as session:
            inbound_path = session.get(SelfOperatedBatch, batch_id).inbound_storage_path
        book = load_workbook(inbound_path)
        sheet = book.worksheets[0]
        columns = [cell.value for cell in sheet[1]]
        for original in list(sheet.iter_rows(min_row=2, values_only=True)):
            values = list(original)
            values[columns.index("关联交货单/调拨单")] = "LN2608179026"
            values[columns.index("积加明细ID")] += "-second"
            sheet.append(values)
        book.save(inbound_path)
        book.close()
        with delivery.open("rb") as upload:
            uploaded = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=self.headers,
                files={"file": (delivery.name, upload)},
            )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)

    def test_saved_target_recomputes_once_and_exports_reason_in_all_formats(self):
        batch_id = self.create_receipt_batch(cumulative=50)
        self.add_second_file(batch_id)
        self.preflight(batch_id)
        run_once(self.database_url, self.storage_root)
        run_once(self.database_url, self.storage_root)
        path = f"/api/batches/{batch_id}"
        before = self.client.get(path, headers=self.headers).json()
        pending = self.client.get(path + "/exceptions", headers=self.headers).json()[0]
        detail_path = f"/api/exceptions/{pending['id']}/inbound-allocation"
        details = self.client.get(detail_path, headers=self.headers).json()
        target = details["items"][0]
        with self.app.state.database.session() as session:
            snapshot = session.get(SelfOperatedBatch, batch_id).receipt_snapshot
        with patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory:
            saved = self.client.put(
                path + "/adjustments",
                headers=self.headers,
                json={
                    "allowances": [
                        {
                            "supplier_code": details["supplier_code"],
                            "sku": pending["sku"],
                            "full_site": pending["full_site"],
                            "file_id": pending["batch_file_id"],
                            "inbound_no": target["inbound_no"],
                            "po_code": target["po_code"],
                            "quantity": 3,
                            "reason": "确认实收",
                        }
                    ]
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            run_once(self.database_url, self.storage_root)
            run_once(self.database_url, self.storage_root)
        factory.assert_not_called()
        after = self.client.get(path, headers=self.headers).json()
        self.assertEqual(after["status"], "succeeded", after)
        self.assertEqual(after["version_ids"], before["version_ids"])
        self.assertEqual(
            after["summary"]["import_total"], before["summary"]["import_total"] + 3
        )
        self.assertEqual(
            after["summary"]["manual_total"], before["summary"]["manual_total"] - 3
        )
        self.assertTrue(after["summary"]["conserved"])
        current = self.client.get(path + "/exceptions", headers=self.headers).json()[0]
        self.assertEqual(
            current["allocated_quantity"], pending["allocated_quantity"] + 3
        )
        self.assertEqual(
            current["overreceipt_allocated_quantity"],
            pending["overreceipt_allocated_quantity"],
        )
        with self.app.state.database.session() as session:
            self.assertEqual(
                session.get(SelfOperatedBatch, batch_id).receipt_snapshot, snapshot
            )
            source = session.get(BatchFile, pending["batch_file_id"])
            self.assertEqual(
                source.import_rows[0]["超收原因"], "追加超收：3（确认实收）"
            )
        for url in (
            path + "/download-merged",
            f"/api/batch-files/{pending['batch_file_id']}/download",
        ):
            downloaded = self.client.get(url, headers=self.headers)
            self.assertEqual(downloaded.status_code, 200, downloaded.text)
            self.assert_export(
                downloaded.content, before["summary"]["manual_total"] - 3
            )
        archive = self.client.get(path + "/download", headers=self.headers)
        self.assertEqual(archive.status_code, 200, archive.text)
        with ZipFile(BytesIO(archive.content)) as zipped:
            workbook = next(
                name for name in zipped.namelist() if name.endswith(".xlsx")
            )
            self.assert_export(
                zipped.read(workbook), before["summary"]["manual_total"] - 3
            )

    def assert_export(self, content, pending_quantity):
        book = load_workbook(BytesIO(content), data_only=True)
        self.assertEqual(book.sheetnames, ["批量入库", "待处理明细"])
        headers = [cell.value for cell in book.worksheets[0][1]]
        reason = book.worksheets[0].cell(2, headers.index("超收原因") + 1).value
        self.assertEqual(reason, "追加超收：3（确认实收）")
        self.assertEqual(book["待处理明细"].cell(2, 10).value, pending_quantity)
        book.close()
