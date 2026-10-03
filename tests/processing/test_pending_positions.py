import unittest
from unittest.mock import patch
import pandas as pd
from delivery_note.processing.models import PENDING_COLUMNS
from delivery_note.processing.pending import (
    enrich_pending_import_rows,
)


class PendingPositionMappingTests(unittest.TestCase):
    def test_unique_values_and_duplicate_msku_mappings_are_exported(self):
        pending_rows = pd.DataFrame(
            [
                ["仓A", "GYS-001", "SKU-A", 10, "AMAZON:SHOP:US", "单据A", "原因A"],
                ["仓B", "GYS-001", "SKU-B", 20, "AMAZON:SHOP:CA", "单据B", "原因B"],
                ["仓C", "GYS-001", "SKU-C", 30, "AMAZON:SHOP:UK", "单据C", "原因C"],
            ],
            columns=[
                "*目的仓",
                "*供应商编码",
                "*SKU",
                "*本次交货量",
                "*站点",
                "单据备注",
                "交货备注",
            ],
        )
        position_rows = pd.DataFrame(
            [
                [" shop:us ", "sku-a", "MSKU-A", "中尾", "备货"],
                ["SHOP:CA", "SKU-B", "MSKU-L", "长尾", "不备货"],
                ["SHOP:CA", "SKU-B", "MSKU-S", "短尾", "备货"],
                ["SHOP:CA", "SKU-B", "MSKU-M", "中尾", "备货"],
            ],
            columns=[
                "店铺-站点",
                "积加SKU",
                "MSKU",
                "规模定位",
                "备货定位",
            ],
        )
        position_rows["已下单可售天数"] = [88.5, 30, 120.25, 60]

        result = enrich_pending_import_rows(pending_rows, position_rows)

        self.assertEqual(result.columns.tolist(), PENDING_COLUMNS)
        self.assertEqual(
            result.loc[0, ["规模定位", "备货定位"]].tolist(),
            ["中尾", "备货"],
        )
        self.assertEqual(
            result.loc[1, "规模定位"],
            '{"MSKU-S":"短尾","MSKU-M":"中尾","MSKU-L":"长尾"}',
        )
        self.assertEqual(
            result.loc[1, "备货定位"],
            '{"MSKU-S":"备货","MSKU-M":"备货","MSKU-L":"不备货"}',
        )
        self.assertEqual(
            result.loc[2, ["规模定位", "备货定位"]].tolist(),
            ["", ""],
        )
        self.assertNotIn("已下单可售天数", result.columns)

    def test_only_pending_position_keys_are_grouped(self):
        pending_rows = pd.DataFrame(
            [
                [
                    "仓A",
                    "GYS-001",
                    "SKU-A",
                    10,
                    "AMAZON:SHOP:US",
                    "单据A",
                    "原因A",
                ]
            ],
            columns=[
                "*目的仓",
                "*供应商编码",
                "*SKU",
                "*本次交货量",
                "*站点",
                "单据备注",
                "交货备注",
            ],
        )
        position_rows = pd.DataFrame(
            [
                ["SHOP:US", "SKU-A", "MSKU-A", "短尾", "备货"],
                *[
                    [
                        "SHOP:CA",
                        f"UNRELATED-{index}",
                        f"MSKU-{index}",
                        "长尾",
                        "不备货",
                    ]
                    for index in range(100)
                ],
            ],
            columns=[
                "店铺-站点",
                "积加SKU",
                "MSKU",
                "规模定位",
                "备货定位",
            ],
        )
        grouped_row_counts = []
        original_groupby = pd.DataFrame.groupby

        def tracked_groupby(frame, *args, **kwargs):
            grouped_row_counts.append(len(frame))
            return original_groupby(frame, *args, **kwargs)

        with patch.object(pd.DataFrame, "groupby", tracked_groupby):
            result = enrich_pending_import_rows(pending_rows, position_rows)

        self.assertEqual(grouped_row_counts, [1])
        self.assertEqual(result.loc[0, "规模定位"], "短尾")
