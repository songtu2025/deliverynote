from dataclasses import replace

from delivery_note.inbound.models import SelfOperatedInboundRequest
from delivery_note.inbound.targeted_allowances import TargetedAllowance
from delivery_note.processing.keys import make_overreceipt_key
from delivery_note.self_operated_inbound import process_self_operated_inbound_batch
from tests.support.inbound import InboundAllocationCase


class TargetedAllowanceTests(InboundAllocationCase):
    def test_supplier_and_full_site_are_part_of_target_identity(self):
        for changes in ({"supplier_code": "OTHER"}, {"full_site": "AMAZON:OTHER:US"}):
            result = self.compute(targets=[replace(self.allowance(), **changes)])
            self.assertEqual((result.import_total, result.pending_total), (7, 7))

    def request(self, quantity=14, source="first"):
        return SelfOperatedInboundRequest(
            source, self.delivery(quantity), ("LN2608179011",), "Yu feng", "GYS-1"
        )

    def allowance(self, quantity=4, reason="确认", **changes):
        return TargetedAllowance(
            supplier_code="GYS-1",
            sku="SKU-A",
            full_site="AMAZON:RIVMOUNT:US",
            inbound_no=changes.get("inbound_no", "WV-1"),
            po_code=changes.get("po_code", "PO-1"),
            remaining=quantity,
            reason=reason,
        )

    def compute(self, requests=None, targets=None, limit=2):
        return process_self_operated_inbound_batch(
            requests or [self.request()],
            self.products(),
            self.inbound(
                [
                    {"应收货": 3, "入库单号": "WV-1", "关联采购单": "PO-1"},
                    {"应收货": 2, "入库单号": "WV-2", "关联采购单": "PO-2"},
                ]
            ),
            overreceipt_limit=limit,
            targeted_allowances=targets or [self.allowance()],
        )

    def test_targeted_po_and_rule_last_po_are_separate_and_conserved(self):
        result = self.compute()
        first, last = result.items[0].result.allocation_rows.to_dict("records")
        self.assertEqual((first["本次入库"], last["本次入库"]), (7, 4))
        self.assertEqual(first["规则内超收数量"], 0)
        self.assertEqual(first["追加超收数量"], 4)
        self.assertEqual(first["超收原因"], "追加超收：4（确认）")
        self.assertEqual(last["超收原因"], "规则允许超收：2")
        self.assertEqual(result.pending_total, 3)
        self.assertEqual(
            result.qualified_total, result.import_total + result.pending_total
        )
        self.assertEqual(result.items[0].result.pending_rows.iloc[0]["追加超收数量"], 4)

    def test_reason_branches_on_the_same_po(self):
        for limit, reason, expected in (
            (2, "确认", "规则允许超收：2；追加超收：4（确认）"),
            (2, "", "规则允许超收：2；追加超收：4"),
            (0, "", "追加超收：4"),
        ):
            with self.subTest(limit=limit, reason=reason):
                result = self.compute(
                    targets=[
                        self.allowance(reason=reason, inbound_no="WV-2", po_code="PO-2")
                    ],
                    limit=limit,
                )
                self.assertEqual(
                    result.items[0].result.allocation_rows.iloc[-1]["超收原因"],
                    expected,
                )

    def test_absent_or_not_allocated_target_never_creates_a_row(self):
        for target in (
            self.allowance(inbound_no="MISSING"),
            self.allowance(inbound_no="WV-2", po_code="OTHER"),
        ):
            result = self.compute(targets=[target], limit=0)
            self.assertEqual((result.import_total, result.pending_total), (5, 9))
        result = self.compute(
            requests=[self.request(8), self.request(8, "second")], limit=0
        )
        self.assertEqual([item.result.import_total for item in result.items], [8, 0])
        self.assertEqual(result.pending_total, 8)

    def test_allowance_consumed_in_file_order_without_mutating_saved_input(self):
        target = self.allowance(6, inbound_no="WV-2", po_code="PO-2")
        requests = [self.request(10), self.request(10, "second")]
        result = self.compute(requests=requests, targets=[target], limit=6)
        self.assertEqual([item.result.import_total for item in result.items], [10, 7])
        self.assertEqual(result.pending_total, 3)
        self.assertEqual(target.remaining, 6)
        reversed_result = self.compute(
            requests=list(reversed(requests)), targets=[target], limit=6
        )
        self.assertEqual(reversed_result.items[0].source_id, "second")
        self.assertEqual(reversed_result.items[0].result.import_total, 10)

    def test_legacy_extra_still_combines_with_rule_on_last_po(self):
        result = process_self_operated_inbound_batch(
            [self.request()],
            self.products(),
            self.inbound([{"应收货": 5}]),
            overreceipt_limit=2,
            extra_overreceipt={
                make_overreceipt_key("Yu feng", "SKU-A", "AMAZON:RIVMOUNT:US"): 4
            },
        )
        self.assertEqual((result.import_total, result.pending_total), (11, 3))
        self.assertIn(
            "人工追加超收：4",
            result.items[0].result.allocation_rows.iloc[0]["超收原因"],
        )
