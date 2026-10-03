from delivery_note.inbound.models import (
    SelfOperatedInboundRequest,
)
from delivery_note.self_operated_inbound import (
    process_self_operated_inbound_batch,
)


from tests.support.inbound import InboundAllocationCase


class InboundBatchesTests(InboundAllocationCase):
    def test_batch_files_share_receivable_balance_in_user_order(self) -> None:
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

    def test_batch_files_share_one_overreceipt_allowance(self) -> None:
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
