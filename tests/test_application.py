import unittest

import pandas as pd

try:
    from delivery_note.application import (
        DeliveryRequest,
        SplitPart,
        process_delivery_batch,
        validate_split,
    )
except ImportError:
    DeliveryRequest = None
    SplitPart = None
    process_delivery_batch = None
    validate_split = None

try:
    from delivery_note.application import project_split
except ImportError:
    project_split = None


class DeliveryBatchTests(unittest.TestCase):
    @staticmethod
    def products():
        return pd.DataFrame(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                }
            ]
        )

    @staticmethod
    def purchases():
        return pd.DataFrame(
            [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 100,
                }
            ]
        )

    @staticmethod
    def request(source_id: str, quantity: int, source_name: str = ""):
        return DeliveryRequest(
            source_id=source_id,
            delivery_rows=pd.DataFrame(
                [{"SKU": "SKU-A", "原始站点": "US", "交货量": quantity}]
            ),
            supplier_name="KuangBiao",
            supplier_code="GYS-023",
            source_name=source_name,
        )

    def setUp(self):
        self.assertIsNotNone(process_delivery_batch, "批次处理服务尚未实现")
        if process_delivery_batch is None:
            self.skipTest("批次处理服务尚未实现")

    def test_purchase_balance_is_shared_in_request_order(self):
        batch = process_delivery_batch(
            [self.request("first", 80), self.request("second", 80)],
            self.products(),
            self.purchases(),
        )

        self.assertEqual(batch.delivery_total, 160)
        self.assertEqual(batch.import_total, 100)
        self.assertEqual(batch.manual_total, 60)
        self.assertEqual(batch.items[0].result.import_total, 80)
        self.assertEqual(batch.items[1].result.import_total, 20)
        self.assertEqual(batch.items[1].result.manual_total, 60)

    def test_changing_order_changes_only_which_source_consumes_balance(self):
        batch = process_delivery_batch(
            [self.request("large", 120), self.request("small", 20)],
            self.products(),
            self.purchases(),
        )
        reversed_batch = process_delivery_batch(
            [self.request("small", 20), self.request("large", 120)],
            self.products(),
            self.purchases(),
        )

        self.assertEqual(batch.import_total, reversed_batch.import_total)
        self.assertEqual(batch.manual_total, reversed_batch.manual_total)
        self.assertEqual(batch.items[0].result.import_total, 100)
        self.assertEqual(reversed_batch.items[0].result.import_total, 20)


    def test_batch_assigns_file_order_and_document_note(self):
        batch = process_delivery_batch(
            [
                self.request(
                    "first",
                    40,
                    "260717-狂飙-A产品交货单-发货96箱.xlsx",
                ),
                self.request(
                    "second",
                    40,
                    "260717-狂飙-B产品交货单-发货86箱.xlsx",
                ),
            ],
            self.products(),
            self.purchases(),
        )

        self.assertEqual([item.file_order for item in batch.items], [1, 2])
        self.assertEqual(
            [item.document_note for item in batch.items],
            ["260717-狂飙-01-96箱", "260717-狂飙-02-86箱"],
        )
        self.assertEqual(
            [item.result.import_rows.iloc[0]["单据备注"] for item in batch.items],
            ["260717-狂飙-01-96箱", "260717-狂飙-02-86箱"],
        )

    def test_failed_batch_does_not_mutate_purchase_input(self):
        purchases = self.purchases()
        deliveries = [
            self.request("valid", 80),
            DeliveryRequest(
                source_id="invalid",
                delivery_rows=pd.DataFrame([{"SKU": "SKU-A", "交货量": 20}]),
                supplier_name="KuangBiao",
                supplier_code="GYS-023",
            ),
        ]

        with self.assertRaisesRegex(ValueError, "交货明细缺少必要字段"):
            process_delivery_batch(deliveries, self.products(), purchases)

        self.assertEqual(purchases.iloc[0]["未交量"], 100)


class SplitValidationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(validate_split, "拆分校验尚未实现")
        if validate_split is None:
            self.skipTest("拆分校验尚未实现")

    def test_split_must_preserve_quantity(self):
        parts = [
            SplitPart(quantity=20, destination="仓A"),
            SplitPart(quantity=10, destination="仓B"),
        ]
        with self.assertRaisesRegex(ValueError, "合计必须等于"):
            validate_split(40, parts)

    def test_split_quantity_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "必须大于 0"):
            validate_split(40, [SplitPart(quantity=40), SplitPart(quantity=0)])

    def test_valid_split_keeps_fields_and_quantity(self):
        parts = [
            SplitPart(quantity=25, destination="仓A", site="AMAZON:SHOP:US"),
            SplitPart(quantity=15, destination="仓B", resolved=False),
        ]

        result = validate_split(40, parts)

        self.assertEqual(sum(part.quantity for part in result), 40)
        self.assertEqual(result[0].destination, "仓A")
        self.assertFalse(result[1].resolved)


class SplitProjectionTests(unittest.TestCase):
    @staticmethod
    def exception():
        return pd.Series(
            {
                "SKU": "SKU-A",
                "原始站点": "US",
                "完整站点": "AMAZON:SEEKWAY:US",
                "目的仓": "水鞋-广州仓",
                "交货量": 40,
                "已自动分配量": 0,
                "人工处理量": 40,
                "异常原因": "超出采购未交量",
            }
        )

    def setUp(self):
        self.assertIsNotNone(project_split, "拆分投影尚未实现")
        if project_split is None:
            self.skipTest("拆分投影尚未实现")

    def test_split_projects_resolved_and_pending_rows_without_quantity_loss(self):
        projection = project_split(
            self.exception(),
            [
                SplitPart(quantity=25, destination="仓A", resolved=True),
                SplitPart(quantity=15, destination="仓B", resolved=False),
            ],
            supplier_code="GYS-023",
            document_note="260717-狂飙-01-96箱",
        )

        self.assertEqual(projection.import_total, 25)
        self.assertEqual(projection.pending_total, 15)
        self.assertEqual(
            projection.import_rows.iloc[0]["*本次交货量"], 25
        )
        self.assertEqual(
            projection.pending_rows.iloc[0]["*本次交货量"], 15
        )
        self.assertEqual(
            projection.import_rows.iloc[0]["单据备注"],
            "260717-狂飙-01-96箱",
        )

    def test_resolved_split_requires_import_destination_and_site(self):
        exception = self.exception().copy()
        exception["目的仓"] = ""
        exception["完整站点"] = ""

        with self.assertRaisesRegex(ValueError, "已解决拆分缺少必要字段"):
            project_split(
                exception,
                [SplitPart(quantity=40, resolved=True)],
                supplier_code="GYS-023",
                document_note="260717-狂飙-01-96箱",
            )


if __name__ == "__main__":
    unittest.main()
