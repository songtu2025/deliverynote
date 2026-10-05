import unittest

import pandas as pd

from delivery_note.processing.models import EXCEPTION_COLUMNS, IMPORT_COLUMNS
from delivery_note.web.models import ExceptionRecord
from delivery_note.web.serializers import exception_row
from delivery_note.workers.export_rows import _consolidate_import_rows


class WorkerExportConsolidationTests(unittest.TestCase):
    def test_exception_projection_preserves_business_columns_and_quantities(
        self,
    ) -> None:
        record = ExceptionRecord(
            batch_file_id=1,
            sku="SKU-A",
            original_site="US",
            full_site="AMAZON:SEEKWAY:US",
            destination="",
            delivery_quantity=40,
            allocated_quantity=0,
            manual_quantity=40,
            reason="超出采购未交量",
        )
        projected = exception_row(record)
        self.assertEqual(list(projected), EXCEPTION_COLUMNS)
        self.assertEqual(
            list(projected.values()),
            ["SKU-A", "US", "AMAZON:SEEKWAY:US", "", 40, 0, 40, "超出采购未交量"],
        )
        record.allocated_quantity = 25
        record.manual_quantity = 15
        updated = exception_row(record)
        self.assertEqual([updated[key] for key in EXCEPTION_COLUMNS[4:7]], [40, 25, 15])
        self.assertEqual(projected["人工处理量"], 40)

    def test_multiple_delivery_notes_are_preserved_in_stable_order(self):
        rows = pd.DataFrame(
            [
                ["仓A", "GYS-001", "SKU-A", 10, "站点A", "单据A", "原因"],
                ["仓A", "GYS-001", "SKU-A", 5, "站点A", "单据A", "原因：5"],
                ["仓A", "GYS-001", "SKU-A", 3, "站点A", "单据A", "其他备注"],
                ["仓A", "GYS-001", "SKU-A", 2, "站点A", "单据A", "原因"],
            ],
            columns=IMPORT_COLUMNS,
        )

        result = _consolidate_import_rows(rows)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["*本次交货量"], 20)
        self.assertEqual(result.iloc[0]["交货备注"], "原因：5；其他备注")
