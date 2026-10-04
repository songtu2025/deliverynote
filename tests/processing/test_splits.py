import unittest

import pandas as pd

from delivery_note.application import SplitPart, project_split, validate_split


class SplitValidationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(validate_split, "拆分校验尚未实现")

    def test_split_must_preserve_quantity(self):
        parts = [
            SplitPart(quantity=20, destination="仓A"),
            SplitPart(quantity=10, destination="仓B"),
        ]
        with self.assertRaisesRegex(ValueError, "合计必须等于"):
            validate_split(40, parts)

    def test_split_quantity_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "必须大于 0"):
            validate_split(40, [SplitPart(quantity=40), SplitPart(quantity=0)])

    def test_valid_split_keeps_fields_and_quantity(self):
        parts = [
            SplitPart(quantity=25, destination="仓A", site="AMAZON:SHOP:US"),
            SplitPart(quantity=15, destination="仓B", resolved=False),
        ]

        result = validate_split(40, parts)

        self.assertEqual(sum(part.quantity for part in result), 40)
        self.assertEqual(result[0].destination, "仓A")
        self.assertFalse(result[1].resolved)


class SplitProjectionTests(unittest.TestCase):
    @staticmethod
    def exception():
        return pd.Series(
            {
                "SKU": "SKU-A",
                "原始站点": "US",
                "完整站点": "AMAZON:SEEKWAY:US",
                "目的仓": "水鞋-广州仓",
                "交货量": 40,
                "已自动分配量": 0,
                "人工处理量": 40,
                "异常原因": "超出采购未交量",
            }
        )

    def setUp(self):
        self.assertIsNotNone(project_split, "拆分投影尚未实现")

    def test_split_projects_resolved_and_pending_rows_without_quantity_loss(self):
        projection = project_split(
            self.exception(),
            [
                SplitPart(quantity=25, destination="仓A", resolved=True),
                SplitPart(quantity=15, destination="仓B", resolved=False),
            ],
            supplier_code="GYS-023",
            document_note="260717-狂飙-01-96箱",
        )

        self.assertEqual(projection.import_total, 25)
        self.assertEqual(projection.pending_total, 15)
        self.assertEqual(projection.import_rows.iloc[0]["*本次交货量"], 25)
        self.assertEqual(projection.pending_rows.iloc[0]["*本次交货量"], 15)
        self.assertEqual(
            projection.import_rows.iloc[0]["单据备注"],
            "260717-狂飙-01-96箱",
        )

    def test_resolved_split_requires_import_destination_and_site(self):
        exception = self.exception().copy()
        exception["目的仓"] = ""
        exception["完整站点"] = ""

        with self.assertRaisesRegex(ValueError, "已解决拆分缺少必要字段"):
            project_split(
                exception,
                [SplitPart(quantity=40, resolved=True)],
                supplier_code="GYS-023",
                document_note="260717-狂飙-01-96箱",
            )
