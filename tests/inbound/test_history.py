from copy import deepcopy
import unittest

from delivery_note.gerpgo import GerpgoClient
from delivery_note.inbound.history import history_frame, receipt_quantity


def inbound_order():
    return {
        "id": "order-1",
        "orderNo": "WV-1",
        "warehouseName": "广州仓",
        "orderStatus": "PART_INBOUND",
        "orderType": "purchase",
        "releatedCode": "LN2608179011",
        "supplierName": "Supplier",
        "purchaseCode": "PO-1",
        "_receipt_rn_type": "0",
        "orderItemResultList": [
            {
                "id": "item-1",
                "sku": "SKU-A",
                "marketName": "SEEKWAY:US",
                "arriveNum": 19,
                "onShelfNum": 3,
                "receiveNum": 3,
                "returnedNum": 0,
                "exceptionNum": 0,
            }
        ],
        "onShelfOrderList": [
            {
                "orderNo": "SJ-1",
                "onshelfedNum": None,
                "onShelfItemList": [
                    {
                        "inboundItemId": "item-1",
                        "onShelfType": "normal",
                        "shelfedNum": 3,
                    }
                ],
            }
        ],
    }


class HistoryTests(unittest.TestCase):
    def test_parent_null_does_not_replace_child_history(self):
        frame = history_frame([inbound_order()])
        self.assertEqual(frame.iloc[0]["已入库"], 3)
        self.assertEqual(frame.iloc[0]["应收货"], 16)
        self.assertEqual(frame.iloc[0]["历史核对问题"], "")

    def test_multiple_shelves_and_closed_difference(self):
        order = inbound_order()
        order["orderStatus"] = "COMPLETED"
        order["orderItemResultList"][0].update(
            arriveNum=49, onShelfNum=48, exceptionNum=1
        )
        order["onShelfOrderList"][0]["onShelfItemList"][0]["shelfedNum"] = 40
        second = deepcopy(order["onShelfOrderList"][0])
        second["orderNo"] = "SJ-2"
        second["onShelfItemList"][0]["shelfedNum"] = 8
        order["onShelfOrderList"].append(second)
        row = history_frame([order]).iloc[0]
        self.assertEqual(row["已入库"], 48)
        self.assertEqual(row["历史核对问题"], "")

    def test_bad_return_missing_and_mismatch_block(self):
        for field, value in (
            ("onShelfNum", None),
            ("onShelfNum", 4),
            ("returnedNum", 1),
            ("exceptionNum", 1),
        ):
            with self.subTest(field=field, value=value):
                order = inbound_order()
                order["orderItemResultList"][0][field] = value
                self.assertTrue(history_frame([order]).iloc[0]["历史核对问题"])
        order = inbound_order()
        order["onShelfOrderList"][0]["onShelfItemList"][0]["onShelfType"] = "bad"
        self.assertTrue(history_frame([order]).iloc[0]["历史核对问题"])

    def test_duplicate_id_conflicts_are_blocked_and_identical_deduplicated(self):
        order = inbound_order()
        self.assertEqual(len(history_frame([order, deepcopy(order)])), 1)
        conflict = deepcopy(order)
        conflict["orderItemResultList"][0]["arriveNum"] = 20
        self.assertIn("冲突", history_frame([order, conflict]).iloc[0]["历史核对问题"])

    def test_invalid_quantity_never_becomes_zero(self):
        for value in (None, "", "NaN", "Infinity", -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                receipt_quantity(value)
        self.assertEqual(receipt_quantity(0), 0)

    def test_api_queries_all_statuses_scopes_and_pages(self):
        calls = []

        def post(url, headers, payload):
            if url.endswith("api_token"):
                return {"code": 200, "data": {"accessToken": "test-token"}}
            calls.append(payload)
            page = payload["page"]
            selected = payload["rnType"] == "0" and payload["orderType"] == "purchase"
            order = {**inbound_order(), "id": str(page)}
            return {
                "code": 200,
                "data": {
                    "rows": [order] if selected else [],
                    "total": 2 if selected else 0,
                },
            }

        client = GerpgoClient(
            "https://fixture.test", "app", "key", post_json=post, sleep=lambda _: None
        )
        orders = client.list_self_operated_inbound_orders(bill_codes=["LN2608179011"])
        self.assertEqual(len(orders), 2)
        self.assertEqual(len(calls), 9)
        self.assertEqual({item["rnType"] for item in calls}, {"0", "1", "3", "4"})
        self.assertTrue(
            all(
                "COMPLETED" in item["orderStatusList"] and item["billType"] == "3"
                for item in calls
            )
        )

    def test_api_rejects_repeated_page_or_scope_escape(self):
        for wrong_scope in (False, True):

            def post(url, headers, payload):
                if url.endswith("api_token"):
                    return {"code": 200, "data": {"accessToken": "test-token"}}
                order = inbound_order()
                if wrong_scope:
                    order["releatedCode"] = "OTHER"
                return {"code": 200, "data": {"rows": [order], "total": 2}}

            client = GerpgoClient(
                "https://fixture.test",
                "app",
                "key",
                post_json=post,
                sleep=lambda _: None,
            )
            with self.assertRaises(ValueError):
                client.list_self_operated_inbound_orders(bill_codes=["LN2608179011"])
