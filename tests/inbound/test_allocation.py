import pandas as pd

from delivery_note.processing.models import OverreceiptAllowance
from delivery_note.exception_reasons import ExceptionReason
from delivery_note.inbound.models import SelfOperatedInboundRequest
from delivery_note.inbound.receipts import prepare_receipts
from delivery_note.processing.keys import make_overreceipt_key
from delivery_note.self_operated_inbound import (
    process_self_operated_inbound,
)


from tests.support.inbound import InboundAllocationCase


class InboundAllocationTests(InboundAllocationCase):
    def test_completed_history_is_pending_without_using_shared_allowance(self):
        inbound = self.inbound(
            [
                {"积加明细ID": "a", "原始应收货": 60, "已入库": 65},
                {"积加明细ID": "b", "原始应收货": 45, "已入库": 45},
            ]
        )
        inbound["入库状态"] = "COMPLETED"
        inbound["仓库类型"] = "0"
        inbound["单据类型"] = "purchase"
        request = SelfOperatedInboundRequest(
            "a", self.delivery(183), ("LN2608179011",), "Yu feng"
        )
        contexts, requests = prepare_receipts([request], self.products(), inbound, {})
        self.assertEqual(contexts["a"]["issue_count"], 0)
        allowance = OverreceiptAllowance(remaining=5, destination_warehouse="")
        allowances = {
            make_overreceipt_key("Yu feng", "SKU-A", "AMAZON:RIVMOUNT:US"): allowance
        }
        result = process_self_operated_inbound(
            requests[0].delivery_lines,
            request.delivery_numbers,
            self.products(),
            inbound,
            "Yu feng",
            overreceipt_allowances=allowances,
        )
        self.assertEqual(
            (result.qualified_total, result.import_total, result.pending_total),
            (73, 0, 73),
        )
        self.assertTrue(result.allocation_rows.empty)
        pending = result.pending_rows.iloc[0]
        self.assertEqual(
            pending["待处理原因"], ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED
        )
        self.assertEqual(
            tuple(
                pending[name]
                for name in (
                    "正常分配数量",
                    "规则内超收数量",
                    "待处理数量",
                    "超过超收规则数量",
                )
            ),
            (105, 5, 73, 73),
        )
        self.assertEqual(allowance.remaining, 5)
        inbound.loc[0, ["入库状态", "应收货"]] = ["WAIT_INBOUND", 0]
        next_result = process_self_operated_inbound(
            self.delivery(5),
            request.delivery_numbers,
            self.products(),
            inbound,
            "Yu feng",
            overreceipt_allowances=allowances,
        )
        self.assertEqual((next_result.import_total, allowance.remaining), (5, 0))

    def test_completed_history_uses_existing_candidate_scope(self):
        for overrides, reason in (
            ({"仓库类型": "2"}, ExceptionReason.INBOUND_ORDER_NOT_FOUND),
            ({"单据类型": "other"}, ExceptionReason.INBOUND_ORDER_NOT_FOUND),
            ({"供应商": "Other"}, ExceptionReason.INBOUND_ORDER_NOT_FOUND),
            ({"平台站点": "AMAZON:OTHER:US"}, ExceptionReason.INBOUND_ORDER_NOT_FOUND),
        ):
            with self.subTest(overrides=overrides):
                inbound = self.inbound(
                    [
                        {
                            "入库状态": "COMPLETED",
                            "原始应收货": 105,
                            "已入库": 110,
                            "仓库类型": "0",
                            "单据类型": "purchase",
                            **overrides,
                        }
                    ]
                )
                result = process_self_operated_inbound(
                    self.delivery(73),
                    ("LN2608179011",),
                    self.products(),
                    inbound,
                    "Yu feng",
                    overreceipt_limit=5,
                )
                pending = result.pending_rows.iloc[0]
                self.assertEqual(pending["待处理原因"], reason)
                self.assertEqual(
                    (pending["正常分配数量"], pending["规则内超收数量"]), (0, 0)
                )

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
