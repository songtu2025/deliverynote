"""自营仓明细取值、空结果、合并顺序和导出守恒。"""

from copy import deepcopy
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import select

from delivery_note.excel.exports import INBOUND_PENDING_COLUMNS
from delivery_note.inbound.models import INBOUND_TEMPLATE_COLUMNS
from delivery_note.web.models import BatchFile, ExceptionRecord
from delivery_note.worker import run_once
from delivery_note.workers.export_inbound import _write_merged_inbound
from delivery_note.workers.export_inputs import _load_inbound_export_inputs
from tests.support.receipt_worker import ReceiptWorkerCase


class InboundExportTests(ReceiptWorkerCase):
    def computed_batch(self, cumulative: int = 50) -> int:
        batch_id = self.create_receipt_batch(cumulative=cumulative)
        self.preflight(batch_id)
        run_once(self.database_url, self.storage_root)
        return batch_id

    def test_single_file_contains_all_fields_and_resolved_records_in_id_order(
        self,
    ) -> None:
        batch_id = self.computed_batch()
        with self.app.state.database.session() as session:
            source = session.scalar(
                select(BatchFile).where(BatchFile.batch_id == batch_id)
            )
            record = session.scalar(
                select(ExceptionRecord).where(
                    ExceptionRecord.batch_file_id == source.id
                )
            )
            record.manual_quantity -= 1
            record.delivery_quantity -= 1
            extra = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-B",
                original_site="US",
                full_site="AMAZON:SEEKWAY:US",
                delivery_quantity=1,
                allocated_quantity=0,
                purchase_allocated_quantity=0,
                overreceipt_allocated_quantity=0,
                manual_quantity=1,
                offline_quantity=1,
                offline_note="已线下登记",
                reason="合成待处理",
                status="resolved",
            )
            session.add(extra)
            session.commit()
            expected = [
                source.original_name,
                source.supplier_name,
                source.document_note,
                record.sku,
                record.original_site,
                record.full_site,
                record.delivery_quantity,
                record.purchase_allocated_quantity,
                record.overreceipt_allocated_quantity,
                record.manual_quantity,
                record.reason,
                0,
                0,
                None,
                record.manual_quantity,
            ]
        run_once(self.database_url, self.storage_root)
        response = self.client.get(
            f"/api/batches/{batch_id}/download", headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, ["批量入库", "待处理明细"])
        self.assertIs(workbook.active, workbook.worksheets[0])
        sheet = workbook["待处理明细"]
        self.assertEqual(list(sheet.values)[0], tuple(INBOUND_PENDING_COLUMNS))
        self.assertEqual(list(sheet.values)[1], tuple(expected))
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual(sheet.cell(3, 4).value, "SKU-B")
        self.assertEqual(
            [sheet.cell(3, column).value for column in (12, 13, 14, 15)],
            [0, 1, "已线下登记", 0],
        )
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertTrue(all(cell.font.bold for cell in sheet[1]))
        self.assertTrue(
            all(
                sheet.column_dimensions[get_column_letter(column)].width >= 18
                for column in range(1, 16)
            )
        )
        for row in (2, 3):
            for column in (7, 8, 9, 10, 12, 13, 15):
                self.assertEqual(sheet.cell(row, column).data_type, "n")
        workbook.close()

    def test_no_pending_still_outputs_header(self) -> None:
        batch_id = self.computed_batch(cumulative=10)
        run_once(self.database_url, self.storage_root)
        response = self.client.get(
            f"/api/batches/{batch_id}/download", headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(
            list(workbook["待处理明细"].values), [tuple(INBOUND_PENDING_COLUMNS)]
        )
        workbook.close()

    def test_merged_contains_every_source_sorted_by_record_id(self) -> None:
        batch_id = self.computed_batch()
        template, sources, _ = _load_inbound_export_inputs(
            self.app.state.database, batch_id
        )
        second = deepcopy(sources[0])
        second["original_name"] = "另一份合成文件.xlsx"
        for row in second["pending_rows"]:
            row["id"] += 1
            row["来源文件"] = second["original_name"]
        sources.insert(0, second)
        frames = [
            pd.DataFrame(source["import_rows"], columns=INBOUND_TEMPLATE_COLUMNS)
            for source in sources
        ]
        _write_merged_inbound(template, self.root, batch_id, sources, frames)
        workbook = load_workbook(self.root / f"batch-{batch_id}-merged.xlsx")
        sheet = workbook["待处理明细"]
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual(
            [row[0] for row in list(sheet.values)[1:]],
            [sources[1]["original_name"], second["original_name"]],
        )
        self.assertEqual(
            sum(row[9] for row in list(sheet.values)[1:]),
            sum(
                source["delivery_total"] - source["import_total"] for source in sources
            ),
        )
        workbook.close()

    def test_single_file_conservation_failure_does_not_publish(self) -> None:
        for field in ("delivery_total", "import_total"):
            with self.subTest(field=field):
                batch_id = self.computed_batch()
                with self.app.state.database.session() as session:
                    source = session.scalar(
                        select(BatchFile).where(BatchFile.batch_id == batch_id)
                    )
                    setattr(source, field, getattr(source, field) + 1)
                    session.commit()
                run_once(self.database_url, self.storage_root)
                batch = self.client.get(
                    f"/api/batches/{batch_id}", headers=self.headers
                ).json()
                self.assertEqual(batch["jobs"]["export"]["status"], "failed")
                self.assertIn("不守恒", batch["jobs"]["export"]["error_message"])
                self.assertFalse(batch["download_ready"])
                self.assertFalse(
                    any(source["download_ready"] for source in batch["files"])
                )
                self.assertFalse(
                    list(
                        (
                            self.storage_root / "batches" / str(batch_id) / "exports"
                        ).rglob("*.xlsx")
                    )
                )

    def test_merged_conservation_failure_raises(self) -> None:
        batch_id = self.computed_batch()
        template, sources, _ = _load_inbound_export_inputs(
            self.app.state.database, batch_id
        )
        frames = [
            pd.DataFrame(source["import_rows"], columns=INBOUND_TEMPLATE_COLUMNS)
            for source in sources
        ]
        sources[0]["delivery_total"] += 1
        with self.assertRaisesRegex(RuntimeError, "合并导出数量不守恒"):
            _write_merged_inbound(template, self.root, batch_id, sources, frames)
        self.assertFalse((self.root / f"batch-{batch_id}-merged.xlsx").exists())

    def test_multiple_transfers_and_partial_offline_use_cumulative_progress(
        self,
    ) -> None:
        batch_id = self.computed_batch()
        run_once(self.database_url, self.storage_root)
        path = f"/api/batches/{batch_id}"
        record = self.client.get(path + "/exceptions", headers=self.headers).json()[0]
        for quantity in (2, 3):
            response = self.client.post(
                path + "/exceptions/transfer-to-delivery",
                headers=self.headers,
                json={
                    "items": [
                        {
                            "exception_id": record["id"],
                            "quantity": quantity,
                            "full_site": record["full_site"],
                        }
                    ]
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            run_once(self.database_url, self.storage_root)
        response = self.client.put(
            f"/api/exceptions/{record['id']}/offline-handling",
            headers=self.headers,
            json={"quantity": 4, "note": "部分线下"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        run_once(self.database_url, self.storage_root)
        response = self.client.get(path + "/download", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(
            list(workbook["待处理明细"].values)[1][11:15],
            (5, 4, "部分线下", record["manual_quantity"] - 9),
        )
        workbook.close()
