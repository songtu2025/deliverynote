"""人工输入经过真实计算与导出，重算不重新访问历史。"""

from io import BytesIO
from unittest.mock import patch

from openpyxl import load_workbook
from sqlalchemy import select

from delivery_note.web.models import BatchFile, SelfOperatedBatch
from delivery_note.worker import run_once
from tests.support.receipt_worker import ReceiptWorkerCase


class ManualHandlingWorkerTests(ReceiptWorkerCase):
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
        saved = self.client.put(
            f"/api/exceptions/{pending['id']}/offline-handling",
            headers=self.headers,
            json={"quantity": pending["manual_quantity"], "note": "线下登记"},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
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
        # 线下处理只在系统内留痕，积加入库导入文件不新增工作表。
        self.assertNotIn("待处理明细", book.sheetnames)
        book.close()
