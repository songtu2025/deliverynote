import unittest

import pandas as pd

from delivery_note.processing.models import (OverreceiptAllowance)
from delivery_note.processing.keys import (make_overreceipt_key)
from delivery_note.inbound.models import (
    SelfOperatedInboundRequest,
)
from delivery_note.self_operated_inbound import (
    process_self_operated_inbound,
    process_self_operated_inbound_batch,
)




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
