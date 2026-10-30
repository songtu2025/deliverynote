import unittest
from unittest.mock import Mock

from delivery_note.gerpgo import GerpgoError
from delivery_note.inbound.purchase_options import collect_purchase_options


class PurchaseOptionsTests(unittest.TestCase):
    def test_keeps_po_and_site_details_but_excludes_other_skus_and_suppliers(self):
        client = Mock()
        client.list_purchase_orders.return_value = [
            {"code": "PO-1", "supplierCode": "GYS-1"}
        ]
        item = {
            "product": "SKU-A",
            "supplierCode": "GYS-1",
            "balanceQuantity": 8,
            "arrivalMarketName": "SEEKWAY:US",
            "deliveryWarehouseName": "仓库甲",
            "arrivalWarehouseName": "目的仓甲",
        }
        client.purchase_order_detail.return_value = {
            "warehouseProcureItemVos": [
                {
                    "procureItemVos": [
                        item,
                        {
                            **item,
                            "arrivalMarketName": "RIVMOUNT:UK",
                            "balanceQuantity": 15,
                        },
                        {**item, "supplierCode": "GYS-2"},
                        {**item, "product": "SKU-B"},
                        {**item, "balanceQuantity": 0},
                        {**item, "balanceQuantity": -3},
                    ]
                }
            ]
        }
        result = collect_purchase_options(client, {("GYS-1", "SKU-A")})
        client.list_purchase_orders.assert_called_once_with(supplier_code="GYS-1")
        self.assertEqual(
            [(r["po_code"], r["site"], r["remaining_quantity"]) for r in result],
            [("PO-1", "AMAZON:SEEKWAY:US", 8), ("PO-1", "AMAZON:RIVMOUNT:UK", 15)],
        )
        self.assertNotIn("price", result[0])
        self.assertEqual(result[0]["warehouse"], "目的仓甲")

    def test_supplier_fields_can_inherit_from_the_order_and_no_orders_is_empty(self):
        client = Mock()
        client.list_purchase_orders.return_value = []
        self.assertEqual(collect_purchase_options(client, {("GYS-1", "SKU-A")}), [])
        client.purchase_order_detail.assert_not_called()
        client.list_purchase_orders.return_value = [
            {"code": "PO-1", "supplierCode": "GYS-1"}
        ]
        client.purchase_order_detail.return_value = {
            "warehouseProcureItemVos": [
                {
                    "deliveryWarehouseName": "仓库甲",
                    "procureItemVos": [
                        {
                            "product": "SKU-A",
                            "arrivalMarketName": "共享",
                            "balanceQuantity": 3,
                        }
                    ],
                }
            ]
        }
        row = collect_purchase_options(client, {("GYS-1", "SKU-A")})[0]
        self.assertEqual(row["site"], "共享")
        self.assertEqual(row["warehouse"], "")

    def test_invalid_quantities_and_failed_details_reject_partial_results(
        self,
    ):
        client = Mock()
        client.list_purchase_orders.return_value = [{"code": "PO-1"}]
        client.purchase_order_detail.return_value = {
            "warehouseProcureItemVos": [
                {
                    "procureItemVos": [
                        {
                            "product": "SKU-A",
                            "supplierCode": "GYS-1",
                            "balanceQuantity": None,
                        }
                    ]
                }
            ]
        }
        with self.assertRaises(GerpgoError):
            collect_purchase_options(client, {("GYS-1", "SKU-A")})
        client.list_purchase_orders.return_value = [{"code": "PO-1"}, {"code": "PO-1"}]
        client.purchase_order_detail.side_effect = None
        client.purchase_order_detail.return_value = {"warehouseProcureItemVos": []}
        with self.assertRaisesRegex(GerpgoError, "重复"):
            collect_purchase_options(client, {("GYS-1", "SKU-A")})
        client.purchase_order_detail.side_effect = GerpgoError("接口不可用")
        with self.assertRaises(GerpgoError):
            collect_purchase_options(client, {("GYS-1", "SKU-A")})

    def test_shared_po_is_fetched_once_and_exact_supplier_sku_pairs_are_enforced(self):
        client = Mock()
        client.list_purchase_orders.return_value = [
            {"code": "PO-1", "supplierCode": "GYS-1"}
        ]
        client.purchase_order_detail.return_value = {
            "warehouseProcureItemVos": [
                {
                    "procureItemVos": [
                        {"supplierCode": supplier, "product": sku, "balanceQuantity": 8}
                        for supplier, sku in [
                            ("GYS-1", "SKU-A"),
                            ("GYS-1", "SKU-B"),
                            ("GYS-2", "SKU-B"),
                        ]
                    ]
                }
            ]
        }
        result = collect_purchase_options(
            client, {("GYS-1", "SKU-A"), ("GYS-2", "SKU-B")}
        )
        self.assertEqual(client.list_purchase_orders.call_count, 2)
        client.purchase_order_detail.assert_called_once_with("PO-1")
        self.assertEqual(
            [(row["supplier_code"], row["sku"]) for row in result],
            [("GYS-1", "SKU-A"), ("GYS-2", "SKU-B")],
        )
