import unittest
from typing import Any

from delivery_note.purchase_sync import (
    compare_purchase_frames,
    map_purchase_order,
    purchase_frame,
)
from delivery_note.self_operated_inbound_sync import (
    map_self_operated_inbound_orders,
)


class PurchaseMappingTests(unittest.TestCase):
    @staticmethod
    def detail(
        balance=12,
        site="SEEKWAY:US",
        supplier_code="GYS-023",
        supplier_name="KuangBiao",
    ):
        return {
            "warehouseProcureItemVos": [
                {
                    "procureItemVos": [
                        {
                            "product": "SKU-A",
                            "supplierCode": supplier_code,
                            "supplierName": supplier_name,
                            "arrivalMarketName": site,
                            "deliveryWarehouseName": "水鞋-广州仓",
                            "balanceQuantity": balance,
                        }
                    ]
                }
            ]
        }

    def test_maps_positive_balance_to_system_purchase_columns(self):
        result = map_purchase_order(
            {"code": "PO-1", "invoicesStatusName": "待交货"},
            self.detail(),
        )

        self.assertEqual(result.raw_count, 1)
        self.assertEqual(result.eligible_count, 1)
        self.assertEqual(result.filtered_count, 0)
        self.assertEqual(result.issues, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(
            result.rows[0],
            {
                "单据状态": "待交货",
                "供应商": "KuangBiao",
                "SKU": "SKU-A",
                "平台站点": "AMAZON:SEEKWAY:US",
                "目的仓": "水鞋-广州仓",
                "未交量": 12,
            },
        )

    def test_filters_fully_delivered_items(self):
        result = map_purchase_order(
            {"code": "PO-1", "invoicesStatusName": "交货中"},
            self.detail(balance=0),
        )

        self.assertEqual(result.rows, [])
        self.assertEqual(result.filtered_count, 1)
        self.assertEqual(result.issues, [])

    def test_uses_complete_api_site_without_product_mapping(self):
        result = map_purchase_order(
            {"code": "PO-1", "invoicesStatusName": "待交货"},
            self.detail(site="RIVMOUNT:US"),
        )

        self.assertEqual(result.issues, [])
        self.assertEqual(result.rows[0]["平台站点"], "AMAZON:RIVMOUNT:US")

    def test_preserves_shared_site_as_non_blocking_warning(self):
        result = map_purchase_order(
            {"code": "PO-1", "invoicesStatusName": "交货中"},
            self.detail(
                site="共享",
                supplier_code="UNKNOWN",
                supplier_name="Unknown",
            ),
        )

        self.assertEqual(result.issues, [])
        self.assertEqual(result.rows[0]["供应商"], "Unknown")
        self.assertEqual(result.rows[0]["平台站点"], "共享")
        self.assertEqual(
            {warning["code"] for warning in result.warnings},
            {"shared_site"},
        )
        self.assertEqual(result.warnings[0]["warehouse"], "水鞋-广州仓")
        self.assertEqual(result.warnings[0]["quantity"], 12)

    def test_blocks_other_incomplete_sites_without_checking_supplier(self):
        result = map_purchase_order(
            {"code": "PO-1", "invoicesStatusName": "交货中"},
            self.detail(
                site="DE站",
                supplier_code="UNKNOWN",
                supplier_name="Unknown",
            ),
        )

        self.assertEqual(result.rows, [])
        self.assertEqual(
            {issue["code"] for issue in result.issues},
            {"site_mapping"},
        )

    def test_compares_aggregated_purchase_balances(self):
        current = purchase_frame(
            [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 10,
                }
            ]
        )
        candidate = current.copy()
        candidate.loc[0, "未交量"] = 8

        difference = compare_purchase_frames(current, candidate)

        self.assertEqual(difference["changed_lines"], 1)
        self.assertEqual(difference["before_quantity"], 10)
        self.assertEqual(difference["after_quantity"], 8)


class SelfOperatedInboundMappingTests(unittest.TestCase):
    @staticmethod
    def order(
        site: str = "SEEKWAY:US", supplier_name: str = "KuangBiao"
    ) -> dict[str, Any]:
        return {
            "orderNo": "IN-1",
            "orderType": "purchase",
            "orderStatus": "WAIT_INBOUND",
            "warehouseName": "自营仓",
            "purchaseCode": "PO-1",
            "releatedCode": "LN-1",
            "supplierCode": "GYS-023",
            "supplierName": supplier_name,
            "orderItemResultList": [
                {
                    "sku": "SKU-A",
                    "marketName": site,
                    "id": 1001,
                    "sourceItemId": 2001,
                    "releatedItemId": 3001,
                    "arriveNum": 12,
                    "maxReceiveNum": 15,
                    "receiveNum": 0,
                    "onShelfNum": 0,
                    "returnedNum": 0,
                }
            ],
        }

    def test_maps_only_waiting_purchase_inbound_rows(self):
        ignored = self.order()
        ignored["orderNo"] = "IN-2"
        ignored["orderStatus"] = "FINISH"

        result = map_self_operated_inbound_orders([self.order(), ignored])

        self.assertEqual(result.raw_count, 2)
        self.assertEqual(result.eligible_count, 1)
        self.assertEqual(result.filtered_count, 1)
        self.assertEqual(result.issues, [])
        self.assertEqual(result.rows[0]["入库单号"], "IN-1")
        self.assertEqual(result.rows[0]["平台站点"], "AMAZON:SEEKWAY:US")
        self.assertEqual(result.rows[0]["应收货"], 12)
        self.assertEqual(result.rows[0]["关联交货单/调拨单"], "LN-1")
        self.assertEqual(result.rows[0]["积加明细ID"], "1001")
        self.assertEqual(result.rows[0]["来源明细ID"], "2001")
        self.assertEqual(result.rows[0]["关联明细ID"], "3001")

    def test_partial_inbound_uses_only_remaining_quantity(self):
        partial = self.order()
        partial["orderStatus"] = "PART_INBOUND"
        partial["orderItemResultList"][0].update(
            {
                "arriveNum": 100,
                "receiveNum": 93,
                "onShelfNum": 93,
                "maxReceiveNum": 120,
            }
        )
        completed_item = self.order()
        completed_item["orderNo"] = "IN-2"
        completed_item["orderStatus"] = "PART_INBOUND"
        completed_item["orderItemResultList"][0].update(
            {"arriveNum": 10, "receiveNum": 10, "onShelfNum": 10}
        )

        result = map_self_operated_inbound_orders([partial, completed_item])

        self.assertEqual(result.raw_count, 2)
        self.assertEqual(result.eligible_count, 1)
        self.assertEqual(result.filtered_count, 1)
        self.assertEqual(result.rows[0]["原始应收货"], 100)
        self.assertEqual(result.rows[0]["应收货"], 7)
        self.assertEqual(result.rows[0]["已收货"], 93)
        self.assertEqual(result.rows[0]["已入库"], 93)

    def test_preserves_shared_site_without_checking_supplier(self):
        shared = self.order(site="共享", supplier_name="")
        shared["orderType"] = "transfer"
        shared["purchaseCode"] = ""

        result = map_self_operated_inbound_orders([shared])

        self.assertEqual(result.issues, [])
        self.assertEqual(result.rows[0]["平台站点"], "共享")
        self.assertEqual(result.rows[0]["关联采购单"], "")
        self.assertEqual(result.rows[0]["供应商"], "")
        warning = result.warnings[0]
        self.assertEqual(warning["code"], "shared_site")
        self.assertEqual(warning["warehouse"], "自营仓")
        self.assertEqual(warning["remaining_quantity"], 12)
        self.assertEqual(warning["purchase_code"], "")
        self.assertEqual(warning["related_code"], "LN-1")

    def test_blocks_missing_purchase_code_for_normal_site(self):
        order = self.order()
        order["purchaseCode"] = ""

        result = map_self_operated_inbound_orders([order])

        self.assertEqual(result.rows, [])
        self.assertEqual(
            {issue["code"] for issue in result.issues},
            {"missing_purchase_code"},
        )

    def test_blocks_incomplete_site_mapping(self):
        result = map_self_operated_inbound_orders([self.order(site="德国站")])

        self.assertEqual(result.rows, [])
        self.assertEqual(
            {issue["code"] for issue in result.issues},
            {"site_mapping"},
        )


if __name__ == "__main__":
    unittest.main()
