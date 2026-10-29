import unittest

from delivery_note.inbound.receipts import prepare_receipts
from delivery_note.inbound.models import SelfOperatedInboundRequest
from tests.support.inbound import InboundAllocationCase
from delivery_note.self_operated_inbound import process_self_operated_inbound_batch

import pandas as pd


class ReceiptTests(InboundAllocationCase):
    def prepare(self, cumulative=19, history=3, status="PART_INBOUND"):
        inbound = self.inbound(
            [
                {
                    "积加明细ID": "item-1",
                    "已入库": history,
                    "原始应收货": 19,
                    "入库状态": status,
                    "历史核对问题": "",
                }
            ]
        )
        request = SelfOperatedInboundRequest(
            "a", self.delivery(cumulative), ("LN2608179011",), "Yu feng"
        )
        return prepare_receipts([request], self.products(), inbound, {})

    def test_cumulative_subtracts_history_once(self):
        contexts, requests = self.prepare()
        self.assertEqual(contexts["a"]["requested_total"], 16)
        self.assertEqual(int(requests[0].delivery_lines["交货量"].sum()), 16)

    def test_zero_is_valid_and_negative_is_blocked(self):
        contexts, requests = self.prepare(3)
        self.assertEqual(contexts["a"]["requested_total"], 0)
        self.assertEqual(int(requests[0].delivery_lines["交货量"].sum()), 0)
        contexts, requests = self.prepare(2)
        self.assertIsNone(contexts["a"]["requested_total"])
        self.assertIn("小于", contexts["a"]["rows"][0]["issue"])
        self.assertEqual(requests, [])

    def test_closed_order_does_not_reopen_difference(self):
        contexts, requests = self.prepare(19, 18, "COMPLETED")
        self.assertIn("已完结", contexts["a"]["rows"][0]["issue"])
        self.assertEqual(requests, [])

    def test_missing_history_is_unknown(self):
        contexts, requests = self.prepare(history=None)
        self.assertIsNone(contexts["a"]["history_total"])
        self.assertEqual(requests, [])

    def test_files_do_not_share_history_but_share_overreceipt(self):
        inbound = self.inbound(
            [
                {
                    "积加明细ID": "a",
                    "已入库": 3,
                    "原始应收货": 19,
                    "应收货": 16,
                    "入库状态": "PART_INBOUND",
                },
                {
                    "积加明细ID": "b",
                    "已入库": 2,
                    "原始应收货": 12,
                    "应收货": 10,
                    "入库状态": "PART_INBOUND",
                    "关联交货单/调拨单": "LN2608179012",
                },
            ]
        )
        deliveries = [
            SelfOperatedInboundRequest(
                name, self.delivery(quantity), (number,), "Yu feng"
            )
            for name, quantity, number in (
                ("a", 22, "LN2608179011"),
                ("b", 16, "LN2608179012"),
            )
        ]
        for order in (deliveries, list(reversed(deliveries))):
            contexts, requests = prepare_receipts(order, self.products(), inbound, {})
            result = process_self_operated_inbound_batch(
                requests, self.products(), inbound, overreceipt_limit=5
            )
            self.assertEqual(
                sum(item["history_total"] for item in contexts.values()), 5
            )
            self.assertEqual(result.qualified_total, 33)
            self.assertEqual((result.import_total, result.pending_total), (31, 2))
            expected = (
                [(19, 0), (12, 2)] if order[0].source_id == "a" else [(14, 0), (17, 2)]
            )
            self.assertEqual(
                [
                    (item.result.import_total, item.result.pending_total)
                    for item in result.items
                ],
                expected,
            )
            self.assertEqual(
                sum(
                    int(item.result.allocation_rows["规则内超收数量"].sum())
                    for item in result.items
                ),
                5,
            )

    def test_overlapping_file_scope_blocks_both_files(self):
        inbound = self.inbound(
            [
                {
                    "积加明细ID": "a",
                    "已入库": 3,
                    "原始应收货": 19,
                    "入库状态": "PART_INBOUND",
                }
            ]
        )
        deliveries = [
            SelfOperatedInboundRequest(
                name, self.delivery(19), ("LN2608179011",), "Yu feng"
            )
            for name in ("a", "b")
        ]
        contexts, requests = prepare_receipts(deliveries, self.products(), inbound, {})
        self.assertEqual(requests, [])
        self.assertTrue(
            all(context["issue_count"] == 1 for context in contexts.values())
        )

    def test_multiple_lns_and_rows_subtract_each_item_once(self):
        inbound = self.inbound(
            [
                {
                    "积加明细ID": "a",
                    "已入库": 3,
                    "原始应收货": 10,
                    "入库状态": "PART_INBOUND",
                },
                {
                    "积加明细ID": "b",
                    "已入库": 2,
                    "原始应收货": 10,
                    "入库状态": "PART_INBOUND",
                    "关联交货单/调拨单": "LN2608179012",
                },
            ]
        )
        delivery = SelfOperatedInboundRequest(
            "a",
            pd.concat([self.delivery(10), self.delivery(9)]),
            ("LN2608179011", "LN2608179012"),
            "Yu feng",
        )
        contexts, _ = prepare_receipts([delivery], self.products(), inbound, {})
        self.assertEqual(
            (
                contexts["a"]["cumulative_total"],
                contexts["a"]["history_total"],
                contexts["a"]["requested_total"],
            ),
            (19, 5, 14),
        )

    def test_other_supplier_and_site_are_not_subtracted(self):
        inbound = self.inbound(
            [
                {
                    "积加明细ID": "a",
                    "已入库": 3,
                    "原始应收货": 10,
                    "入库状态": "PART_INBOUND",
                },
                {
                    "积加明细ID": "b",
                    "已入库": 7,
                    "原始应收货": 10,
                    "入库状态": "PART_INBOUND",
                    "供应商": "Other",
                },
                {
                    "积加明细ID": "c",
                    "已入库": 8,
                    "原始应收货": 10,
                    "入库状态": "PART_INBOUND",
                    "平台站点": "AMAZON:OTHER:US",
                },
            ]
        )
        delivery = SelfOperatedInboundRequest(
            "a", self.delivery(19), ("LN2608179011",), "Yu feng"
        )
        contexts, _ = prepare_receipts([delivery], self.products(), inbound, {})
        self.assertEqual(contexts["a"]["history_total"], 3)

    def test_site_choice_does_not_leak_to_another_file(self):
        products = self.products().copy()
        other = products.copy()
        other["店铺/站点"] = "OTHER:US"
        products = pd.concat([products, other])
        rows = []
        for number in ("LN2608179011", "LN2608179012"):
            for site in ("AMAZON:RIVMOUNT:US", "AMAZON:OTHER:US"):
                rows.append(
                    {
                        "积加明细ID": number + site,
                        "已入库": 3,
                        "原始应收货": 19,
                        "入库状态": "PART_INBOUND",
                        "关联交货单/调拨单": number,
                        "平台站点": site,
                    }
                )
        deliveries = [
            SelfOperatedInboundRequest(name, self.delivery(19), (number,), "Yu feng")
            for name, number in (("a", "LN2608179011"), ("b", "LN2608179012"))
        ]
        contexts, requests = prepare_receipts(
            deliveries,
            products,
            self.inbound(rows),
            {"a": {("SKU-A", "US"): "AMAZON:RIVMOUNT:US"}},
        )
        self.assertEqual(contexts["a"]["requested_total"], 16)
        self.assertIsNone(contexts["b"]["requested_total"])
        self.assertEqual(requests, [])
        contexts, requests = prepare_receipts(
            deliveries,
            products,
            self.inbound(rows),
            {"a": {("SKU-A", "US"): "AMAZON:REMOVED:US"}},
        )
        self.assertIn("不在候选范围", contexts["a"]["rows"][0]["issue"])
        self.assertEqual(len(contexts["a"]["rows"][0]["candidates"]), 2)
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
