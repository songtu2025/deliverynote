from tests.support.allocation import AllocationCase
from delivery_note.pipeline import process_data


class AllocationTests(AllocationCase):
    def test_excess_delivery_only_sends_excess_to_manual_processing(self):
        result = process_data(
            self.delivery(120),
            self.products(),
            self.purchases(
                [
                    {
                        "单据状态": "交货中",
                        "供应商": "KuangBiao",
                        "SKU": "SKU-A",
                        "平台站点": "AMAZON:SEEKWAY:US",
                        "目的仓": "水鞋-广州仓",
                        "未交量": 80,
                    }
                ]
            ),
            "KuangBiao",
        )

        self.assertEqual(result.import_total, 80)
        self.assertEqual(result.manual_total, 40)
        self.assertEqual(result.import_rows.iloc[0]["交货备注"], "超出采购未交量：40")
        self.assertEqual(result.exception_rows.iloc[0]["异常原因"], "超出采购未交量")

    def test_short_tail_rule_imports_only_the_configured_overreceipt_quantity(self):
        purchases = self.purchases(
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
        result = process_data(
            self.delivery(165),
            self.products(),
            purchases,
            "KuangBiao",
            overreceipt_allowances=self.overreceipt_allowances(purchases=purchases),
        )

        self.assertEqual(result.delivery_total, 165)
        self.assertEqual(result.import_total, 150)
        self.assertEqual(result.manual_total, 15)
        self.assertEqual(
            result.import_rows[["*本次交货量", "交货备注"]].to_dict("records"),
            [
                {"*本次交货量": 100, "交货备注": ""},
                {"*本次交货量": 50, "交货备注": "规则允许超收：50"},
            ],
        )
        self.assertEqual(result.exception_rows.iloc[0]["异常原因"], "超出允许超收量")
        self.assertEqual(result.exception_rows.iloc[0]["人工处理量"], 15)
        self.assertEqual(result.exception_rows.iloc[0]["正常采购分配量"], 100)
        self.assertEqual(result.exception_rows.iloc[0]["超收规则分配量"], 50)
        self.assertEqual(result.exception_rows.iloc[0]["超收剩余额度"], 0)

    def test_blank_scale_does_not_create_overreceipt_allowance(self):
        positions = self.positions()
        positions.loc[:, "规模定位"] = ""
        allowances = self.overreceipt_allowances(positions=positions)

        result = process_data(
            self.delivery(165),
            self.products(),
            self.purchases(
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
            ),
            "KuangBiao",
            overreceipt_allowances=allowances,
        )

        self.assertEqual(result.import_total, 100)
        self.assertEqual(result.manual_total, 65)

    def test_conflicting_msku_scales_do_not_create_overreceipt_allowance(self):
        positions = self.positions(
            [
                {
                    "店铺-站点": "SEEKWAY:US",
                    "积加SKU": "SKU-A",
                    "MSKU": "MSKU-S",
                    "规模定位": "短尾",
                    "备货定位": "备货",
                    "已下单可售天数": 30,
                },
                {
                    "店铺-站点": "SEEKWAY:US",
                    "积加SKU": "SKU-A",
                    "MSKU": "MSKU-M",
                    "规模定位": "中尾",
                    "备货定位": "备货",
                    "已下单可售天数": 30,
                },
            ]
        )

        self.assertEqual(self.overreceipt_allowances(positions=positions), {})

    def test_warehouse_outside_whitelist_does_not_create_overreceipt_allowance(self):
        self.assertEqual(
            self.overreceipt_allowances(allowed_warehouses={"手套-广州仓"}),
            {},
        )
