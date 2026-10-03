from tests.support.allocation import AllocationCase
import unittest
from unittest.mock import patch
import pandas as pd
import delivery_note.pipeline as pipeline_module
from delivery_note.pipeline import (process_data)
from delivery_note.processing.models import (PENDING_COLUMNS)
from delivery_note.processing.pending import (
        build_manual_import_rows,
        enrich_pending_import_rows,
    )






class AllocationTests(AllocationCase):


















    def test_purchase_ledger_aggregates_and_filters_all_matching_dimensions(self):
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:CA",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )
        purchases = self.purchases(
            [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "供应商成品本地仓",
                    "未交量": 2,
                },
                {
                    "单据状态": "交货中",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "供应商成品本地仓",
                    "未交量": "3",
                },
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 4,
                },
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:CA",
                    "目的仓": "加拿大仓",
                    "未交量": 6,
                },
                {
                    "单据状态": "待交货",
                    "供应商": "OtherSupplier",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "供应商成品本地仓",
                    "未交量": 100,
                },
                {
                    "单据状态": "已完成",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "已完成仓",
                    "未交量": 100,
                },
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "无效仓",
                    "未交量": "不是数字",
                },
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "零余额仓",
                    "未交量": 0,
                },
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "负余额仓",
                    "未交量": -5,
                },
            ]
        )
        delivery = pd.DataFrame(
            [
                {"SKU": "SKU-A", "原始站点": "US", "交货量": 10},
                {"SKU": "SKU-A", "原始站点": "CA", "交货量": 7},
            ]
        )

        result = process_data(
            delivery,
            products,
            purchases,
            "KuangBiao",
            "GYS-023",
        )

        self.assertEqual(
            result.import_rows.groupby(["*站点", "*目的仓"])[
                "*本次交货量"
            ].sum().to_dict(),
            {
                ("AMAZON:SEEKWAY:CA", "加拿大仓"): 6,
                ("AMAZON:SEEKWAY:US", "供应商成品本地仓"): 5,
                ("AMAZON:SEEKWAY:US", "水鞋-广州仓"): 4,
            },
        )
        self.assertEqual(
            result.import_rows["*目的仓"].tolist(),
            ["加拿大仓", "供应商成品本地仓", "水鞋-广州仓"],
        )
        self.assertEqual(result.delivery_total, 17)
        self.assertEqual(result.import_total, 15)
        self.assertEqual(result.manual_total, 2)
        self.assertEqual(
            result.exception_rows[["人工处理量", "异常原因"]].to_dict("records"),
            [
                {"人工处理量": 1, "异常原因": "超出采购未交量"},
                {"人工处理量": 1, "异常原因": "超出采购未交量"},
            ],
        )

    def test_direct_process_calls_build_independent_purchase_ledgers(self):
        with patch.object(
            pipeline_module,
            "build_purchase_balance_ledger",
            wraps=pipeline_module.build_purchase_balance_ledger,
        ) as build_ledger:
            first = process_data(
                self.delivery(100),
                self.products(),
                self.purchases(),
                "KuangBiao",
            )
            second = process_data(
                self.delivery(100),
                self.products(),
                self.purchases(),
                "KuangBiao",
            )

        self.assertEqual(build_ledger.call_count, 2)
        self.assertEqual((first.import_total, second.import_total), (100, 100))


class ManualImportMappingTests(unittest.TestCase):

    def test_excess_quantity_maps_to_official_import_columns(self):
        exceptions = pd.DataFrame(
            [
                [
                    "SKU-A",
                    "US",
                    "AMAZON:SEEKWAY:US",
                    "水鞋-广州仓",
                    120,
                    80,
                    40,
                    "超出采购未交量",
                ]
            ],
            columns=[
                "SKU",
                "原始站点",
                "完整站点",
                "目的仓",
                "交货量",
                "已自动分配量",
                "人工处理量",
                "异常原因",
            ],
        )

        result = build_manual_import_rows(exceptions, "KuangBiao")

        self.assertEqual(
            result.to_dict("records"),
            [
                {
                    "*目的仓": "水鞋-广州仓",
                    "*供应商编码": "KuangBiao",
                    "*SKU": "SKU-A",
                    "*本次交货量": 40,
                    "*站点": "AMAZON:SEEKWAY:US",
                    "单据备注": "",
                    "交货备注": "超出采购未交量：40",
                }
            ],
        )

    def test_missing_or_ambiguous_site_stays_blank(self):
        exceptions = pd.DataFrame(
            [
                ["SKU-A", "US", "", "", 20, 0, 20, "产品信息未匹配"],
                [
                    "SKU-B",
                    "US",
                    "AMAZON:OTHER:US、AMAZON:SEEKWAY:US",
                    "",
                    30,
                    0,
                    30,
                    "产品信息站点不唯一",
                ],
            ],
            columns=[
                "SKU",
                "原始站点",
                "完整站点",
                "目的仓",
                "交货量",
                "已自动分配量",
                "人工处理量",
                "异常原因",
            ],
        )

        result = build_manual_import_rows(exceptions, "KuangBiao")

        self.assertEqual(result["*站点"].tolist(), ["", ""])
        self.assertEqual(result["*目的仓"].tolist(), ["", ""])
        self.assertEqual(
            result["交货备注"].tolist(),
            [
                "产品信息未匹配；原始站点：US",
                "产品信息站点不唯一：AMAZON:OTHER:US、AMAZON:SEEKWAY:US",
            ],
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


if __name__ == "__main__":
    unittest.main()
