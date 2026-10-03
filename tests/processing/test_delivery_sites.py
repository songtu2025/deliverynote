import unittest
import pandas as pd
from delivery_note.processing.delivery_sites import normalize_delivery_sheet


class DeliveryNormalizationTests(unittest.TestCase):
    def test_normalize_detail_sheet(self):

        sheet = pd.DataFrame(
            [
                ["SKU-A", 5, "CA站"],
                ["SKU-A", 10, "US站"],
                ["SKU-A", 2, "CA站"],
                ["合计", None, None],
                ["次品问题描述", None, None],
            ],
            columns=["积加SKU", "数量", "站点"],
        )

        result = normalize_delivery_sheet(sheet)

        self.assertEqual(
            result.to_dict("records"),
            [
                {"SKU": "SKU-A", "原始站点": "CA", "交货量": 7},
                {"SKU": "SKU-A", "原始站点": "US", "交货量": 10},
            ],
        )

    def test_normalize_detail_rejects_incomplete_row(self):
        sheet = pd.DataFrame(
            [["SKU-A", 12, "US站"], ["SKU-B", None, "US站"]],
            columns=["积加SKU", "数量", "站点"],
        )

        with self.assertRaisesRegex(ValueError, "第 6 行"):
            normalize_delivery_sheet(sheet)

    def test_normalize_detail_rejects_fractional_quantity(self):
        sheet = pd.DataFrame(
            [["SKU-A", 1.5, "US站"]],
            columns=["积加SKU", "数量", "站点"],
        )

        with self.assertRaisesRegex(ValueError, "第 5 行"):
            normalize_delivery_sheet(sheet)
