from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

import delivery_note.pipeline as pipeline_module

try:
    from delivery_note.config import SupplierIdentity, resolve_supplier
    from delivery_note.pipeline import (
        BatchResult,
        normalize_delivery_sheet,
        process_data,
    )
except ImportError:
    resolve_supplier = None
    SupplierIdentity = None
    BatchResult = None
    normalize_delivery_sheet = None
    process_data = None

try:
    from delivery_note.pipeline import (
        OverreceiptPolicy,
        build_overreceipt_allowances,
    )
except ImportError:
    OverreceiptPolicy = None
    build_overreceipt_allowances = None

try:
    from delivery_note.config import build_document_note
except ImportError:
    build_document_note = None

try:
    from delivery_note.pipeline import (
        PENDING_COLUMNS,
        build_manual_import_rows,
        enrich_pending_import_rows,
    )
except ImportError:
    PENDING_COLUMNS = []
    enrich_pending_import_rows = None
    build_manual_import_rows = None


class SupplierConfigTests(unittest.TestCase):
    def test_resolve_supplier_from_delivery_filename(self):
        self.assertIsNotNone(resolve_supplier, "供应商识别函数尚未实现")
        if resolve_supplier is None:
            return

        supplier_rows = pd.DataFrame(
            [
                {"供应商编号": "GYS-023", "供应商名称": "KuangBiao", "状态": "启用"},
                {"供应商编号": "GYS-027", "供应商名称": "Zhangdun", "状态": "启用"},
            ]
        )
        supplier = resolve_supplier(
            Path("260628 掌盾-SIMARI交货单.xlsx"), supplier_rows
        )

        self.assertEqual(supplier, SupplierIdentity(name="Zhangdun", code="GYS-027"))

    def test_build_document_note_generates_stable_group_sequence(self):
        self.assertIsNotNone(build_document_note, "单据备注生成函数尚未实现")
        if build_document_note is None:
            return

        supplier_rows = pd.DataFrame(
            [
                {"供应商编号": "GYS-023", "供应商名称": "KuangBiao", "状态": "启用"},
                {"供应商编号": "GYS-026", "供应商名称": "Yu feng", "状态": "启用"},
            ]
        )
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            first = directory_path / "260717-狂飙-A产品交货单-发货96箱.xlsx"
            second = directory_path / "260717-狂飙-B产品交货单-发货86箱.xlsx"
            other_supplier = directory_path / "260717 裕枫SEEKWAY交货单-交货151箱.xls"
            for path in (first, second, other_supplier):
                path.touch()

            first_note = build_document_note(first, supplier_rows)
            second_note = build_document_note(second, supplier_rows)
            other_note = build_document_note(other_supplier, supplier_rows)

        self.assertEqual(first_note, "260717-狂飙-01-96箱")
        self.assertEqual(second_note, "260717-狂飙-02-86箱")
        self.assertEqual(other_note, "260717-裕枫-01-151箱")

    def test_unknown_supplier_filename_is_rejected(self):
        self.assertIsNotNone(resolve_supplier, "供应商识别函数尚未实现")
        if resolve_supplier is None:
            return

        supplier_rows = pd.DataFrame(
            [{"供应商编号": "GYS-023", "供应商名称": "KuangBiao", "状态": "启用"}]
        )
        with self.assertRaisesRegex(ValueError, "无法从文件名识别供应商"):
            resolve_supplier(Path("未知供应商交货单.xlsx"), supplier_rows)


class DeliveryNormalizationTests(unittest.TestCase):
    def test_normalize_current_summary_sheet(self):
        self.assertIsNotNone(normalize_delivery_sheet, "交货单归一化函数尚未实现")
        if normalize_delivery_sheet is None:
            return

        sheet = pd.DataFrame(
            [
                ["SKU-A", 5, 10, 15],
                ["SKU-B", 0, 8, 8],
                ["总计", 5, 18, 23],
            ],
            columns=["SKU", "CA站", "US站", "总计"],
        )

        result = normalize_delivery_sheet(sheet)

        self.assertEqual(
            result.to_dict("records"),
            [
                {"SKU": "SKU-A", "原始站点": "CA", "交货量": 5},
                {"SKU": "SKU-A", "原始站点": "US", "交货量": 10},
                {"SKU": "SKU-B", "原始站点": "US", "交货量": 8},
            ],
        )

    def test_normalize_summary_with_vendor_specific_sku_header(self):
        sheet = pd.DataFrame(
            [["SKU-A", 12, 12]],
            columns=["积加SKU", "US站", "总计"],
        )

        result = normalize_delivery_sheet(sheet)

        self.assertEqual(
            result.to_dict("records"),
            [{"SKU": "SKU-A", "原始站点": "US", "交货量": 12}],
        )


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(process_data, "核心处理函数尚未实现")
        if process_data is None:
            self.skipTest("核心处理函数尚未实现")

    @staticmethod
    def delivery(quantity=100):
        return pd.DataFrame([{"SKU": "SKU-A", "原始站点": "US", "交货量": quantity}])

    @staticmethod
    def products(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                }
            ]
        )

    @staticmethod
    def purchases(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 150,
                }
            ]
        )

    @staticmethod
    def positions(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "店铺-站点": "SEEKWAY:US",
                    "积加SKU": "SKU-A",
                    "MSKU": "MSKU-A",
                    "规模定位": "短尾",
                    "备货定位": "备货",
                    "已下单可售天数": 30,
                }
            ]
        )

    @staticmethod
    def overreceipt_policy(allowed_warehouses=None):
        return OverreceiptPolicy(
            short_tail_limit=50,
            medium_tail_limit=20,
            long_tail_limit=10,
            allowed_warehouses=frozenset(allowed_warehouses or {"水鞋-广州仓"}),
        )

    def overreceipt_allowances(
        self,
        purchases=None,
        positions=None,
        allowed_warehouses=None,
    ):
        self.assertIsNotNone(OverreceiptPolicy, "超收规则尚未实现")
        self.assertIsNotNone(build_overreceipt_allowances, "超收额度计算尚未实现")
        return build_overreceipt_allowances(
            purchases if purchases is not None else self.purchases(),
            positions if positions is not None else self.positions(),
            self.overreceipt_policy(allowed_warehouses),
        )

    def test_partial_delivery_is_fully_importable(self):
        result = process_data(
            self.delivery(100), self.products(), self.purchases(), "KuangBiao"
        )

        self.assertIsInstance(result, BatchResult)
        self.assertEqual(result.delivery_total, 100)
        self.assertEqual(result.import_total, 100)
        self.assertEqual(result.manual_total, 0)
        self.assertEqual(result.import_rows.iloc[0]["*目的仓"], "水鞋-广州仓")
        self.assertEqual(result.import_rows.iloc[0]["交货备注"], "")

    def test_purchase_matches_supplier_name_but_import_uses_supplier_code(self):
        result = process_data(
            self.delivery(20),
            self.products(),
            self.purchases(),
            "KuangBiao",
            "GYS-023",
        )

        self.assertEqual(result.import_rows.iloc[0]["*供应商编码"], "GYS-023")

    def test_excess_delivery_only_sends_excess_to_manual_processing(self):
        result = process_data(
            self.delivery(120),
            self.products(),
            self.purchases(
                [
                    {
                        "单据状态": "交货中",
                        "供应商": "KuangBiao",
                        "SKU": "SKU-A",
                        "平台站点": "AMAZON:SEEKWAY:US",
                        "目的仓": "水鞋-广州仓",
                        "未交量": 80,
                    }
                ]
            ),
            "KuangBiao",
        )

        self.assertEqual(result.import_total, 80)
        self.assertEqual(result.manual_total, 40)
        self.assertEqual(result.import_rows.iloc[0]["交货备注"], "超出采购未交量：40")
        self.assertEqual(result.exception_rows.iloc[0]["异常原因"], "超出采购未交量")

    def test_short_tail_rule_imports_only_the_configured_overreceipt_quantity(self):
        purchases = self.purchases(
            [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 100,
                }
            ]
        )
        result = process_data(
            self.delivery(165),
            self.products(),
            purchases,
            "KuangBiao",
            overreceipt_allowances=self.overreceipt_allowances(purchases=purchases),
        )

        self.assertEqual(result.delivery_total, 165)
        self.assertEqual(result.import_total, 150)
        self.assertEqual(result.manual_total, 15)
        self.assertEqual(
            result.import_rows[["*本次交货量", "交货备注"]].to_dict("records"),
            [
                {"*本次交货量": 100, "交货备注": ""},
                {"*本次交货量": 50, "交货备注": "规则允许超收：50"},
            ],
        )
        self.assertEqual(result.exception_rows.iloc[0]["异常原因"], "超出允许超收量")
        self.assertEqual(result.exception_rows.iloc[0]["人工处理量"], 15)
        self.assertEqual(result.exception_rows.iloc[0]["正常采购分配量"], 100)
        self.assertEqual(result.exception_rows.iloc[0]["超收规则分配量"], 50)
        self.assertEqual(result.exception_rows.iloc[0]["超收剩余额度"], 0)

    def test_blank_scale_does_not_create_overreceipt_allowance(self):
        positions = self.positions()
        positions.loc[:, "规模定位"] = ""
        allowances = self.overreceipt_allowances(positions=positions)

        result = process_data(
            self.delivery(165),
            self.products(),
            self.purchases(
                [
                    {
                        "单据状态": "待交货",
                        "供应商": "KuangBiao",
                        "SKU": "SKU-A",
                        "平台站点": "AMAZON:SEEKWAY:US",
                        "目的仓": "水鞋-广州仓",
                        "未交量": 100,
                    }
                ]
            ),
            "KuangBiao",
            overreceipt_allowances=allowances,
        )

        self.assertEqual(result.import_total, 100)
        self.assertEqual(result.manual_total, 65)

    def test_conflicting_msku_scales_do_not_create_overreceipt_allowance(self):
        positions = self.positions(
            [
                {
                    "店铺-站点": "SEEKWAY:US",
                    "积加SKU": "SKU-A",
                    "MSKU": "MSKU-S",
                    "规模定位": "短尾",
                    "备货定位": "备货",
                    "已下单可售天数": 30,
                },
                {
                    "店铺-站点": "SEEKWAY:US",
                    "积加SKU": "SKU-A",
                    "MSKU": "MSKU-M",
                    "规模定位": "中尾",
                    "备货定位": "备货",
                    "已下单可售天数": 30,
                },
            ]
        )

        self.assertEqual(self.overreceipt_allowances(positions=positions), {})

    def test_warehouse_outside_whitelist_does_not_create_overreceipt_allowance(self):
        self.assertEqual(
            self.overreceipt_allowances(allowed_warehouses={"手套-广州仓"}),
            {},
        )

    def test_product_mapping_ambiguity_is_sent_to_manual_processing(self):
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
                    "店铺/站点": "OTHER:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_data(
            self.delivery(20), products, self.purchases(), "KuangBiao"
        )

        self.assertEqual(result.import_total, 0)
        self.assertEqual(result.manual_total, 20)
        self.assertEqual(
            result.exception_rows.iloc[0]["异常原因"], "产品信息站点不唯一"
        )

    def test_locked_product_site_resolves_ambiguity(self):
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "OTHER:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "不锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_data(
            self.delivery(20), products, self.purchases(), "KuangBiao"
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.manual_total, 0)
        self.assertEqual(result.import_rows.iloc[0]["*站点"], "AMAZON:SEEKWAY:US")

    def test_unavailable_purchase_status_is_not_allocated(self):
        purchases = self.purchases(
            [
                {
                    "单据状态": "已完成",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 150,
                }
            ]
        )

        result = process_data(
            self.delivery(20), self.products(), purchases, "KuangBiao"
        )

        self.assertEqual(result.import_total, 0)
        self.assertEqual(result.manual_total, 20)
        self.assertEqual(
            result.exception_rows.iloc[0]["异常原因"], "未找到可交货采购需求"
        )

    def test_supplier_local_warehouse_is_allocated_first(self):
        purchases = self.purchases(
            [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 80,
                },
                {
                    "单据状态": "交货中",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "供应商成品本地仓",
                    "未交量": 30,
                },
            ]
        )

        result = process_data(
            self.delivery(130), self.products(), purchases, "KuangBiao"
        )

        self.assertEqual(
            result.import_rows[["*目的仓", "*本次交货量"]].to_dict("records"),
            [
                {"*目的仓": "供应商成品本地仓", "*本次交货量": 30},
                {"*目的仓": "水鞋-广州仓", "*本次交货量": 80},
            ],
        )
        self.assertEqual(result.manual_total, 20)
        self.assertEqual(result.import_rows.iloc[0]["交货备注"], "")
        self.assertEqual(result.import_rows.iloc[1]["交货备注"], "超出采购未交量：20")
        self.assertEqual(result.exception_rows.iloc[0]["异常原因"], "超出采购未交量")
        self.assertEqual(result.exception_rows.iloc[0]["目的仓"], "水鞋-广州仓")

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
    def setUp(self):
        self.assertIsNotNone(build_manual_import_rows, "异常待处理映射函数尚未实现")
        if build_manual_import_rows is None:
            self.skipTest("异常待处理映射函数尚未实现")

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
    def setUp(self):
        self.assertIsNotNone(
            enrich_pending_import_rows, "待处理定位信息匹配函数尚未实现"
        )
        if enrich_pending_import_rows is None:
            self.skipTest("待处理定位信息匹配函数尚未实现")

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
                [" shop:us ", "sku-a", "MSKU-A", "中尾", "备货", 88.5],
                ["SHOP:CA", "SKU-B", "MSKU-L", "长尾", "不备货", 30],
                ["SHOP:CA", "SKU-B", "MSKU-S", "短尾", "备货", 120.25],
                ["SHOP:CA", "SKU-B", "MSKU-M", "中尾", "备货", 60],
            ],
            columns=[
                "店铺-站点",
                "积加SKU",
                "MSKU",
                "规模定位",
                "备货定位",
                "已下单可售天数",
            ],
        )

        result = enrich_pending_import_rows(pending_rows, position_rows)

        self.assertEqual(result.columns.tolist(), PENDING_COLUMNS)
        self.assertEqual(
            result.loc[0, ["规模定位", "备货定位", "已下单可售天数"]].tolist(),
            ["中尾", "备货", 88.5],
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
            result.loc[1, "已下单可售天数"],
            '{"MSKU-S":120.25,"MSKU-M":60,"MSKU-L":30}',
        )
        self.assertEqual(
            result.loc[2, ["规模定位", "备货定位", "已下单可售天数"]].tolist(),
            ["", "", ""],
        )

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
                ["SHOP:US", "SKU-A", "MSKU-A", "短尾", "备货", 90],
                *[
                    [
                        "SHOP:CA",
                        f"UNRELATED-{index}",
                        f"MSKU-{index}",
                        "长尾",
                        "不备货",
                        30,
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
                "已下单可售天数",
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
