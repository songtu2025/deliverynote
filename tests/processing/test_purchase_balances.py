from tests.support.allocation import AllocationCase
from unittest.mock import patch
import pandas as pd
import delivery_note.pipeline as pipeline_module
from delivery_note.pipeline import process_data


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
            result.import_rows.groupby(["*站点", "*目的仓"])["*本次交货量"]
            .sum()
            .to_dict(),
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
