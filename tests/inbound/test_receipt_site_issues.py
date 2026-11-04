import pandas as pd

from delivery_note.inbound.models import SelfOperatedInboundRequest
from delivery_note.inbound.receipts import prepare_receipts
from delivery_note.self_operated_inbound import process_self_operated_inbound_batch
from tests.support.inbound import InboundAllocationCase


class ReceiptSiteIssueTests(InboundAllocationCase):
    def test_product_site_issues_keep_all_quantity_without_blocking(self):
        for reason in ("产品信息未匹配", "产品信息站点不唯一"):
            with self.subTest(reason=reason):
                products = self.products()
                if reason == "产品信息站点不唯一":
                    extra = pd.concat([products, products], ignore_index=True)
                    extra["SKU"] = "SKU-B"
                    extra["店铺/站点"] = ["RIVMOUNT:US", "OTHER:US"]
                    products = pd.concat([products, extra], ignore_index=True)
                rows = [
                    {
                        "SKU": sku,
                        "平台站点": site,
                        "积加明细ID": sku + site,
                        "已入库": 3,
                        "原始应收货": 19,
                        "入库状态": "PART_INBOUND",
                    }
                    for sku, site in (
                        ("SKU-A", "AMAZON:RIVMOUNT:US"),
                        ("SKU-B", "AMAZON:RIVMOUNT:US"),
                        ("SKU-B", "AMAZON:OTHER:US"),
                    )
                ]
                inbound = self.inbound(rows)
                other = self.delivery(4)
                other["SKU"] = "SKU-B"
                request = SelfOperatedInboundRequest(
                    "a",
                    pd.concat([self.delivery(19), other]),
                    ("LN2608179011",),
                    "Yu feng",
                )
                contexts, requests = prepare_receipts([request], products, inbound, {})
                context = contexts["a"]
                self.assertEqual(
                    tuple(
                        context[name]
                        for name in (
                            "cumulative_total",
                            "history_total",
                            "requested_total",
                            "unconfirmed_count",
                            "issue_count",
                        )
                    ),
                    (23, 3, 20, 1, 0),
                )
                row = context["rows"][1]
                self.assertEqual(
                    (row["issue"], row["history"], row["requested"]), ("", None, 4)
                )
                self.assertIn("历史未确认，全部进入待处理", row["notice"])
                self.assertEqual(row["reason"], reason)
                result = process_self_operated_inbound_batch(
                    requests, products, inbound
                )
                self.assertEqual(
                    (result.qualified_total, result.import_total, result.pending_total),
                    (20, 16, 4),
                )
                pending = result.items[0].result.pending_rows.iloc[0]
                self.assertEqual(pending["待处理原因"], reason)
                if reason == "产品信息站点不唯一":
                    self.assertEqual(len(row["candidates"]), 2)
                    self.assertEqual(pending["完整站点"].split("、"), row["candidates"])

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
        self.assertEqual(contexts["b"]["requested_total"], 19)
        self.assertEqual(contexts["b"]["unconfirmed_count"], 1)
        self.assertEqual(len(requests), 2)
        contexts, requests = prepare_receipts(
            deliveries,
            products,
            self.inbound(rows),
            {"a": {("SKU-A", "US"): "AMAZON:REMOVED:US"}},
        )
        self.assertIn("不在候选范围", contexts["a"]["rows"][0]["issue"])
        self.assertEqual(len(contexts["a"]["rows"][0]["candidates"]), 2)
        self.assertEqual(requests, [])
