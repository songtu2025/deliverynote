from tests.support.allocation import AllocationCase
from delivery_note.processing.models import BatchResult
from delivery_note.pipeline import process_data


class AllocationTests(AllocationCase):
    def test_partial_delivery_is_fully_importable(self):
        result = process_data(
            self.delivery(100), self.products(), self.purchases(), "KuangBiao"
        )

        self.assertIsInstance(result, BatchResult)
        self.assertEqual(result.delivery_total, 100)
        self.assertEqual(result.import_total, 100)
        self.assertEqual(result.manual_total, 0)
        self.assertEqual(result.import_rows.iloc[0]["*目的仓"], "水鞋-广州仓")
        self.assertEqual(result.import_rows.iloc[0]["交货备注"], "")

    def test_purchase_matches_supplier_name_but_import_uses_supplier_code(self):
        result = process_data(
            self.delivery(20),
            self.products(),
            self.purchases(),
            "KuangBiao",
            "GYS-023",
        )

        self.assertEqual(result.import_rows.iloc[0]["*供应商编码"], "GYS-023")

    def test_product_mapping_ambiguity_is_sent_to_manual_processing(self):
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "OTHER:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_data(
            self.delivery(20), products, self.purchases(), "KuangBiao"
        )

        self.assertEqual(result.import_total, 0)
        self.assertEqual(result.manual_total, 20)
        self.assertEqual(
            result.exception_rows.iloc[0]["异常原因"], "产品信息站点不唯一"
        )

    def test_locked_product_site_resolves_ambiguity(self):
        products = self.products(
            [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "OTHER:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "不锁",
                },
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                },
            ]
        )

        result = process_data(
            self.delivery(20), products, self.purchases(), "KuangBiao"
        )

        self.assertEqual(result.import_total, 20)
        self.assertEqual(result.manual_total, 0)
        self.assertEqual(result.import_rows.iloc[0]["*站点"], "AMAZON:SEEKWAY:US")

    def test_unavailable_purchase_status_is_not_allocated(self):
        purchases = self.purchases(
            [
                {
                    "单据状态": "已完成",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 150,
                }
            ]
        )

        result = process_data(
            self.delivery(20), self.products(), purchases, "KuangBiao"
        )

        self.assertEqual(result.import_total, 0)
        self.assertEqual(result.manual_total, 20)
        self.assertEqual(
            result.exception_rows.iloc[0]["异常原因"], "未找到可交货采购需求"
        )

    def test_supplier_local_warehouse_is_allocated_first(self):
        purchases = self.purchases(
            [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 80,
                },
                {
                    "单据状态": "交货中",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "供应商成品本地仓",
                    "未交量": 30,
                },
            ]
        )

        result = process_data(
            self.delivery(130), self.products(), purchases, "KuangBiao"
        )

        self.assertEqual(
            result.import_rows[["*目的仓", "*本次交货量"]].to_dict("records"),
            [
                {"*目的仓": "供应商成品本地仓", "*本次交货量": 30},
                {"*目的仓": "水鞋-广州仓", "*本次交货量": 80},
            ],
        )
        self.assertEqual(result.manual_total, 20)
        self.assertEqual(result.import_rows.iloc[0]["交货备注"], "")
        self.assertEqual(result.import_rows.iloc[1]["交货备注"], "超出采购未交量：20")
        self.assertEqual(result.exception_rows.iloc[0]["异常原因"], "超出采购未交量")
        self.assertEqual(result.exception_rows.iloc[0]["目的仓"], "水鞋-广州仓")
