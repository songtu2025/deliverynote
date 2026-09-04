from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from openpyxl import Workbook

from delivery_note.excel_io import (
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
)
from delivery_note.pipeline import OverreceiptAllowance, make_overreceipt_key
from delivery_note.self_operated_inbound import (
    SelfOperatedInboundRequest,
    normalize_self_operated_delivery_sheet,
    process_self_operated_inbound,
    process_self_operated_inbound_batch,
)


class SelfOperatedDeliveryNormalizationTests(unittest.TestCase):
    def test_delivery_numbers_are_extracted_independently(self):
        sheet = pd.DataFrame(
            [
                {
                    "积加SKU": "SKU-A",
                    "实收数量": 20,
                    "站点": "US站",
                    "品牌": "SIMARI",
                    "交货单号": "LN2608179012",
                },
                {
                    "积加SKU": "SKU-A",
                    "实收数量": 30,
                    "站点": "US站",
                    "品牌": "SIMARI",
                    "交货单号": "LN2608179011",
                },
                {
                    "积加SKU": "SKU-B",
                    "实收数量": 10,
                    "站点": "US站",
                    "品牌": "SEEKWAY",
                    "交货单号": "单上没有，来货有",
                },
            ]
        )

        result = normalize_self_operated_delivery_sheet(sheet)

        self.assertEqual(
            result.delivery_lines.to_dict("records"),
            [
                {"SKU": "SKU-A", "原始站点": "US", "交货量": 50},
                {"SKU": "SKU-B", "原始站点": "US", "交货量": 10},
            ],
        )
        self.assertEqual(
            result.delivery_numbers,
            ("LN2608179011", "LN2608179012"),
        )
        self.assertEqual(result.invalid_delivery_values, ("单上没有，来货有",))

    def test_missing_received_quantity_is_rejected(self):
        sheet = pd.DataFrame(
            [
                {
                    "积加SKU": "SKU-A",
                    "实收数量": None,
                    "站点": "US站",
                    "交货单号": "LN2608179011",
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "实收数量存在空值或无效值"):
            normalize_self_operated_delivery_sheet(sheet)

    def test_excel_readers_load_detail_and_inbound_rows(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            delivery_path = root / "交货单.xlsx"
            delivery_book = Workbook()
            delivery_sheet = delivery_book.active
            delivery_sheet.title = "明细"
            delivery_sheet.append(["交货单标题"])
            delivery_sheet.append([])
            delivery_sheet.append(["说明"])
            delivery_sheet.append(["积加SKU", "实收数量", "站点", "交货单号"])
            delivery_sheet.append(["SKU-A", 20, "US站", "LN2608179011"])
            delivery_book.save(delivery_path)

            inbound_path = root / "自营仓.xlsx"
            inbound_book = Workbook()
            inbound_sheet = inbound_book.active
            inbound_sheet.append(
                [
                    "入库单号",
                    "入库仓",
                    "SKU",
                    "平台站点",
                    "关联交货单/调拨单",
                    "关联采购单",
                    "应收货",
                    "供应商",
                ]
            )
            inbound_sheet.append(
                [
                    "WV-1",
                    "水鞋-广州仓",
                    "SKU-A",
                    "AMAZON:RIVMOUNT:US",
                    "LN2608179011",
                    "PO2601010001",
                    30,
                    "Yu feng",
                ]
            )
            inbound_book.save(inbound_path)

            delivery = read_self_operated_delivery_workbook(delivery_path)
            inbound = read_self_operated_inbound_workbook(inbound_path)

        self.assertEqual(delivery.delivery_lines.iloc[0]["交货量"], 20)
        self.assertEqual(delivery.delivery_numbers, ("LN2608179011",))
        self.assertEqual(inbound.iloc[0]["应收货"], 30)


class SelfOperatedAllocationTests(unittest.TestCase):
    @staticmethod
    def products(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                }
            ]
        )

    @staticmethod
    def delivery(quantity=100):
        return pd.DataFrame([{"SKU": "SKU-A", "原始站点": "US", "交货量": quantity}])

    @staticmethod
    def inbound(rows):
        defaults = {
            "入库单号": "WV-1",
            "入库仓": "水鞋-广州仓",
            "SKU": "SKU-A",
            "平台站点": "AMAZON:RIVMOUNT:US",
            "关联交货单/调拨单": "LN2608179011",
            "关联采购单": "PO2601010001",
            "应收货": 100,
            "供应商": "Yu feng",
        }
        return pd.DataFrame([{**defaults, **row} for row in rows])

    def test_product_mapping_uses_locked_product_site_not_brand(self):
        inbound = self.inbound([{}])

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            self.products(),
            inbound,
            "Yu feng",
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.pending_total, 0)
        self.assertEqual(
            result.allocation_rows.iloc[0]["平台站点"],
            "AMAZON:RIVMOUNT:US",
        )

    def test_inbound_candidate_resolves_multiple_locked_product_sites(self):
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SIMARI:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            products,
            self.inbound([{}]),
            "Yu feng",
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.pending_total, 0)
        self.assertEqual(
            result.allocation_rows.iloc[0]["平台站点"],
            "AMAZON:RIVMOUNT:US",
        )

    def test_missing_delivery_number_rejects_partial_matching(self):
        inbound = self.inbound([{}])

        with self.assertRaisesRegex(ValueError, "缺少交货单号.*9012"):
            process_self_operated_inbound(
                self.delivery(20),
                ("LN2608179011", "LN2608179012"),
                self.products(),
                inbound,
                "Yu feng",
            )

    def test_normal_quantity_is_allocated_by_po_then_source_order(self):
        inbound = self.inbound(
            [
                {
                    "入库单号": "WV-3",
                    "关联交货单/调拨单": "LN2608179021",
                    "关联采购单": "PO2601010001",
                    "应收货": 30,
                },
                {
                    "入库单号": "WV-2",
                    "关联交货单/调拨单": "LN2608179014",
                    "关联采购单": "PO2601010002",
                    "应收货": 20,
                },
                {
                    "入库单号": "WV-1",
                    "关联交货单/调拨单": "LN2608179014",
                    "关联采购单": "PO2601010001",
                    "应收货": 40,
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(80),
            ("LN2608179014", "LN2608179021"),
            self.products(),
            inbound,
            "Yu feng",
        )

        self.assertEqual(
            result.allocation_rows[
                ["关联交货单/调拨单", "关联采购单", "本次入库"]
            ].to_dict("records"),
            [
                {
                    "关联交货单/调拨单": "LN2608179021",
                    "关联采购单": "PO2601010001",
                    "本次入库": 30,
                },
                {
                    "关联交货单/调拨单": "LN2608179014",
                    "关联采购单": "PO2601010001",
                    "本次入库": 40,
                },
                {
                    "关联交货单/调拨单": "LN2608179014",
                    "关联采购单": "PO2601010002",
                    "本次入库": 10,
                },
            ],
        )

    def test_overreceipt_is_shared_once_and_attached_to_last_po(self):
        inbound = self.inbound(
            [
                {
                    "入库单号": "WV-1",
                    "关联交货单/调拨单": "LN2608179014",
                    "关联采购单": "PO2601010001",
                    "应收货": 30,
                },
                {
                    "入库单号": "WV-2",
                    "关联交货单/调拨单": "LN2608179021",
                    "关联采购单": "PO2601010002",
                    "应收货": 60,
                },
            ]
        )
        allowances = {
            make_overreceipt_key(
                "Yu feng",
                "SKU-A",
                "AMAZON:RIVMOUNT:US",
            ): OverreceiptAllowance(remaining=5, destination_warehouse=""),
        }

        result = process_self_operated_inbound(
            self.delivery(100),
            ("LN2608179014", "LN2608179021"),
            self.products(),
            inbound,
            "Yu feng",
            overreceipt_allowances=allowances,
        )

        self.assertEqual(result.qualified_total, 100)
        self.assertEqual(result.import_total, 95)
        self.assertEqual(result.pending_total, 5)
        self.assertEqual(
            result.allocation_rows[
                ["正常分配数量", "规则内超收数量", "本次入库"]
            ].to_dict("records"),
            [
                {"正常分配数量": 30, "规则内超收数量": 0, "本次入库": 30},
                {"正常分配数量": 60, "规则内超收数量": 5, "本次入库": 65},
            ],
        )
        self.assertEqual(result.allocation_rows.iloc[-1]["入库库位"], "未分配库位")
        self.assertTrue(pd.isna(result.allocation_rows.iloc[-1]["本次退货"]))
        self.assertEqual(
            result.pending_rows.iloc[0]["超过超收规则数量"],
            5,
        )
        self.assertEqual(allowances[next(iter(allowances))].remaining, 0)

    def test_same_delivery_overreceipt_is_attached_to_last_po(self):
        inbound = self.inbound(
            [
                {
                    "入库单号": "WV-2",
                    "关联采购单": "PO2601010002",
                    "应收货": 60,
                },
                {
                    "入库单号": "WV-1",
                    "关联采购单": "PO2601010001",
                    "应收货": 30,
                },
            ]
        )
        allowances = {
            make_overreceipt_key(
                "Yu feng",
                "SKU-A",
                "AMAZON:RIVMOUNT:US",
            ): OverreceiptAllowance(remaining=5, destination_warehouse=""),
        }

        result = process_self_operated_inbound(
            self.delivery(100),
            ("LN2608179011",),
            self.products(),
            inbound,
            "Yu feng",
            overreceipt_allowances=allowances,
        )

        self.assertEqual(
            result.allocation_rows[
                ["关联采购单", "正常分配数量", "规则内超收数量", "本次入库"]
            ].to_dict("records"),
            [
                {
                    "关联采购单": "PO2601010001",
                    "正常分配数量": 30,
                    "规则内超收数量": 0,
                    "本次入库": 30,
                },
                {
                    "关联采购单": "PO2601010002",
                    "正常分配数量": 60,
                    "规则内超收数量": 5,
                    "本次入库": 65,
                },
            ],
        )
        self.assertEqual(result.pending_total, 5)

    def test_uniform_overreceipt_limit_is_applied(self):
        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            self.products(),
            self.inbound([{"应收货": 12}]),
            "Yu feng",
            overreceipt_limit=5,
        )

        self.assertEqual(result.import_total, 17)
        self.assertEqual(result.pending_total, 3)
        self.assertEqual(
            result.allocation_rows.iloc[0]["规则内超收数量"],
            5,
        )

    def test_multiple_inbound_candidates_stay_pending_for_manual_selection(self):
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
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            products,
            self.inbound(
                [
                    {},
                    {
                        "入库单号": "WV-2",
                        "平台站点": "AMAZON:SEEKWAY:US",
                    },
                ]
            ),
            "Yu feng",
        )

        self.assertEqual(result.import_total, 0)
        self.assertEqual(result.pending_total, 20)
        self.assertEqual(
            result.pending_rows.iloc[0]["待处理原因"],
            "产品信息站点不唯一",
        )
        self.assertEqual(
            set(result.pending_rows.iloc[0]["完整站点"].split("、")),
            {"AMAZON:RIVMOUNT:US", "AMAZON:SEEKWAY:US"},
        )

    def test_manual_site_selection_recomputes_allocation(self):
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
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )
        inbound = self.inbound(
            [
                {},
                {
                    "入库单号": "WV-2",
                    "平台站点": "AMAZON:SEEKWAY:US",
                },
            ]
        )

        result = process_self_operated_inbound(
            self.delivery(20),
            ("LN2608179011",),
            products,
            inbound,
            "Yu feng",
            site_overrides={
                ("SKU-A", "US"): "AMAZON:SEEKWAY:US",
            },
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.pending_total, 0)
        self.assertEqual(
            result.allocation_rows.iloc[0]["平台站点"],
            "AMAZON:SEEKWAY:US",
        )

    def test_manual_site_selection_must_use_filtered_candidate(self):
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
                    "店铺/站点": "RIVMOUNT:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )
        inbound = self.inbound(
            [
                {},
                {
                    "入库单号": "WV-2",
                    "平台站点": "AMAZON:SEEKWAY:US",
                },
            ]
        )

        with self.assertRaisesRegex(ValueError, "人工选择站点不在候选范围"):
            process_self_operated_inbound(
                self.delivery(20),
                ("LN2608179011",),
                products,
                inbound,
                "Yu feng",
                site_overrides={("SKU-A", "US"): "AMAZON:SIMARI:US"},
            )

    def test_batch_files_share_receivable_balance_in_user_order(self):
        requests = [
            SelfOperatedInboundRequest(
                source_id="first",
                delivery_lines=self.delivery(8),
                delivery_numbers=("LN2608179011",),
                supplier_name="Yu feng",
            ),
            SelfOperatedInboundRequest(
                source_id="second",
                delivery_lines=self.delivery(8),
                delivery_numbers=("LN2608179011",),
                supplier_name="Yu feng",
            ),
        ]

        result = process_self_operated_inbound_batch(
            requests,
            self.products(),
            self.inbound([{"应收货": 10}]),
        )

        self.assertEqual(
            [
                (
                    item.source_id,
                    item.result.import_total,
                    item.result.pending_total,
                )
                for item in result.items
            ],
            [("first", 8, 0), ("second", 2, 6)],
        )
        self.assertEqual(result.qualified_total, 16)
        self.assertEqual(result.import_total, 10)
        self.assertEqual(result.pending_total, 6)

        reversed_result = process_self_operated_inbound_batch(
            reversed(requests),
            self.products(),
            self.inbound([{"应收货": 10}]),
        )
        self.assertEqual(
            [
                (
                    item.source_id,
                    item.result.import_total,
                    item.result.pending_total,
                )
                for item in reversed_result.items
            ],
            [("second", 8, 0), ("first", 2, 6)],
        )

    def test_batch_files_share_one_overreceipt_allowance(self):
        result = process_self_operated_inbound_batch(
            [
                SelfOperatedInboundRequest(
                    source_id="first",
                    delivery_lines=self.delivery(8),
                    delivery_numbers=("LN2608179011",),
                    supplier_name="Yu feng",
                ),
                SelfOperatedInboundRequest(
                    source_id="second",
                    delivery_lines=self.delivery(10),
                    delivery_numbers=("LN2608179011",),
                    supplier_name="Yu feng",
                ),
            ],
            self.products(),
            self.inbound([{"应收货": 10}]),
            overreceipt_limit=5,
        )

        first, second = result.items
        self.assertEqual(first.result.import_total, 8)
        self.assertEqual(second.result.import_total, 7)
        self.assertEqual(second.result.pending_total, 3)
        self.assertEqual(
            int(second.result.allocation_rows["规则内超收数量"].sum()),
            5,
        )
        self.assertEqual(result.qualified_total, 18)
        self.assertEqual(result.import_total, 15)
        self.assertEqual(result.pending_total, 3)


if __name__ == "__main__":
    unittest.main()
