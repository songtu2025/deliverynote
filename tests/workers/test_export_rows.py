import unittest

import pandas as pd

from delivery_note.processing.models import IMPORT_COLUMNS
from delivery_note.workers.export_rows import _consolidate_import_rows


class WorkerExportConsolidationTests(unittest.TestCase):
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
