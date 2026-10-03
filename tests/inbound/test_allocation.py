import pandas as pd

from delivery_note.processing.models import OverreceiptAllowance
from delivery_note.processing.keys import make_overreceipt_key
from delivery_note.self_operated_inbound import (
    process_self_operated_inbound,
)


from tests.support.inbound import InboundAllocationCase


class InboundAllocationTests(InboundAllocationCase):
    def test_normal_quantity_is_allocated_by_po_then_source_order(self) -> None:
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

    def test_overreceipt_is_shared_once_and_attached_to_last_po(self) -> None:
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

    def test_same_delivery_overreceipt_is_attached_to_last_po(self) -> None:
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

    def test_uniform_overreceipt_limit_is_applied(self) -> None:
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
