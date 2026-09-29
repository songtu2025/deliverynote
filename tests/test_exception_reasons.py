import unittest

from delivery_note.exception_reasons import exception_reason_code


class ExceptionReasonTests(unittest.TestCase):
    def test_existing_reasons_keep_their_codes_for_historical_batches(self):
        existing = {
            "产品信息未匹配": "product_not_found",
            "产品信息站点不唯一": "ambiguous_product_site",
            "超出采购未交量": "purchase_balance_exceeded",
            "未找到可交货采购需求": "purchase_not_found",
            "超出允许超收量": "overreceipt_limit_exceeded",
            "未找到自营仓入库单": "inbound_order_not_found",
            "供应商不一致": "supplier_mismatch",
            "PO名称为空": "po_name_missing",
            "应收货无效": "receivable_invalid",
            "超出应收货": "receivable_exceeded",
        }
        for label, code in existing.items():
            with self.subTest(label=label):
                self.assertEqual(exception_reason_code(label), code)

    def test_unknown_reason_has_no_special_behavior(self):
        self.assertEqual(exception_reason_code("历史未知原因"), "unknown")


if __name__ == "__main__":
    unittest.main()
