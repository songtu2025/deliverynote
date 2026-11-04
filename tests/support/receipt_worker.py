"""累计实收集成测试共用的合成批次与预检入口。"""

from openpyxl import load_workbook
from delivery_note.web.models import InputVersion, SelfOperatedBatch
from delivery_note.worker import run_once
from tests.support.worker import WorkerCase


class ReceiptWorkerCase(WorkerCase):
    def create_receipt_batch(self, cumulative=19, history=3, *, managed=False):
        delivery = self.create_self_operated_delivery(
            self.root / "狂飙-累计.xlsx", cumulative
        )
        inbound = self.create_self_operated_inbound(self.root / "完整历史.xlsx")
        book = load_workbook(inbound)
        sheet = book.worksheets[0]
        columns = [cell.value for cell in sheet[1]]
        for row in (2, 3):
            for column, value in (
                ("已入库", history),
                ("原始应收货", 19),
                ("应收货", 19 - history),
            ):
                sheet.cell(row, columns.index(column) + 1, value)
        book.save(inbound)
        book.close()
        with delivery.open("rb") as upload, inbound.open("rb") as source:
            result = self.client.post(
                "/api/self-operated-batches",
                headers=self.headers,
                data={"name": "累计实收验收"},
                files={
                    "delivery_file": (delivery.name, upload),
                    "inbound_file": (inbound.name, source),
                },
            )
        self.assertEqual(result.status_code, 201, result.text)
        batch_id = result.json()["id"]
        if managed:
            with self.app.state.database.session() as session:
                profile = session.get(SelfOperatedBatch, batch_id)
                session.add(
                    InputVersion(
                        kind="self_operated_inbound",
                        name="API来源",
                        original_name="API来源.xlsx",
                        storage_path=profile.inbound_storage_path,
                        created_by=result.json()["created_by"],
                        active=True,
                    )
                )
                session.commit()
        return batch_id

    def preflight(self, batch_id):
        result = self.client.post(
            f"/api/batches/{batch_id}/preflight", headers=self.headers
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "queued")
        run_once(self.database_url, self.storage_root)
        return self.client.get(f"/api/batches/{batch_id}", headers=self.headers).json()
