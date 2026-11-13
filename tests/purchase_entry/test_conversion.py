"""采购日期列、供应商和唯一映射的业务规则。"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import load_workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904, to_excel

from tests.purchase_entry.support import convert, make_files


class PurchaseConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = make_files(Path(self.directory.name))

    def change(
        self, kind: str, coordinate: str, value: str | int | float | None
    ) -> None:
        book = load_workbook(self.paths[kind])
        book.worksheets[0][coordinate] = value
        book.save(self.paths[kind])

    def test_columns_keep_order_zero_gap_and_tk_bypass(self) -> None:
        result = convert(self.paths)
        preview = result.to_preview()
        self.assertEqual(preview["supplier_code"], "SUP001")
        self.assertEqual(preview["order_prefix"], "JQ2026040304")
        self.assertEqual(preview["row_count"], 3)
        self.assertEqual(preview["total_quantity"], 60)
        self.assertEqual(preview["skipped_zero_count"], 3)
        self.assertEqual(
            [batch["order_number"] for batch in preview["batches"]],
            ["JQ202604030401", "JQ202604030403"],
        )
        first, second, third = result.rows
        self.assertEqual(first.site, "AMAZON:店铺/US")
        self.assertEqual(first.msku, "MSKU-A")
        self.assertEqual(first.note, "美国备注")
        self.assertEqual(first.unit_price, Decimal("1.25"))
        self.assertEqual(second.warehouse, "TK本地仓")
        self.assertEqual(second.site, "共享")
        self.assertEqual(third.msku, "SKU-B")
        self.assertEqual(result.row_count, 3)
        self.assertEqual(result.batch_count, 2)
        self.assertEqual(result.total_quantity, 60)

    def test_total_marker_in_column_a_stops_before_terms(self) -> None:
        self.change("source", "B11", None)
        self.change("source", "A11", "合计")
        self.assertEqual(convert(self.paths).row_count, 3)

    def test_supplier_match_is_exact_enabled_and_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "供应商"):
            convert(self.paths, "甲厂扩展名-采购单.xlsx")
        self.change("supplier", "C2", "停用")
        with self.assertRaisesRegex(ValueError, "供应商"):
            convert(self.paths)

    def test_ambiguous_product_and_warehouse_are_not_first_match(self) -> None:
        book = load_workbook(self.paths["product"])
        book.worksheets[0].append(
            ["US", "SKU-A", "其他店铺/US", "OTHER", "合成品类", ""]
        )
        book.save(self.paths["product"])
        with self.assertRaisesRegex(ValueError, "SKU-A.*多个|SKU-A.*不唯一"):
            convert(self.paths)
        self.change("product", "A4", None)
        book = load_workbook(self.paths["product"])
        book.worksheets[0].delete_rows(4)
        book.save(self.paths["product"])
        book = load_workbook(self.paths["warehouse"])
        book.worksheets[0].append(["SKU-A", "其他仓"])
        book.save(self.paths["warehouse"])
        with self.assertRaisesRegex(ValueError, "SKU-A.*仓库"):
            convert(self.paths)

    def test_missing_product_fails_only_for_positive_rows(self) -> None:
        self.change("product", "B3", "OTHER")
        self.assertEqual(convert(self.paths).to_preview()["total_quantity"], 60)
        self.change("product", "B2", "OTHER2")
        with self.assertRaisesRegex(ValueError, "SKU-A.*商品"):
            convert(self.paths)

    def test_blank_sku_does_not_silently_drop_quantities(self) -> None:
        self.change("source", "B9", None)
        with self.assertRaisesRegex(ValueError, "B9.*SKU"):
            convert(self.paths)

    def test_product_error_names_source_quantity_cell(self) -> None:
        self.change("product", "B2", "OTHER")
        with self.assertRaisesRegex(ValueError, "G9.*SKU-A"):
            convert(self.paths)

    def test_invalid_quantities_fail_with_cell_location(self) -> None:
        for value in (-1, "错误", 1.25):
            with self.subTest(value=value):
                self.change("source", "H9", value)
                with self.assertRaisesRegex(ValueError, "H9.*数量"):
                    convert(self.paths)

    def test_uncached_quantity_formula_is_not_treated_as_zero(self) -> None:
        self.change("source", "G9", "=5+5")
        with self.assertRaisesRegex(ValueError, "G9.*公式.*缓存"):
            convert(self.paths)

    def test_missing_batch_metadata_never_drops_quantities(self) -> None:
        for coordinate, value, message in (
            ("G8", "=DATE(2026,5,1)", "G8.*公式.*缓存"),
            ("G8", None, "G8.*日期"),
            ("G7", None, "G7.*站点"),
        ):
            with self.subTest(coordinate=coordinate, value=value):
                self.paths = make_files(Path(self.directory.name))
                self.change("source", coordinate, value)
                with self.assertRaisesRegex(ValueError, message):
                    convert(self.paths)

    def test_integer_float_tolerance_does_not_truncate(self) -> None:
        self.change("source", "G9", 9.999999999)
        self.assertEqual(convert(self.paths).rows[0].quantity, 10)

    def test_price_uses_header_and_decimal_validation(self) -> None:
        self.change("source", "F6", "  单价(含包装)  ")
        self.assertEqual(convert(self.paths).rows[0].unit_price, Decimal("1.25"))
        self.change("source", "F9", "错误")
        with self.assertRaisesRegex(ValueError, "F9.*单价"):
            convert(self.paths)

    def test_dates_support_epoch_serial_and_text_without_sorting(self) -> None:
        book = load_workbook(self.paths["source"])
        book.epoch = CALENDAR_MAC_1904
        sheet = book.worksheets[0]
        sheet["G8"] = to_excel(datetime(2026, 6, 1), book.epoch)
        sheet["G8"].number_format = "General"
        sheet["I8"] = "2026/05/01"
        book.save(self.paths["source"])
        batches = convert(self.paths).to_preview()["batches"]
        self.assertEqual(
            [batch["delivery_date"] for batch in batches],
            ["2026-06-01", "2026-05-01"],
        )

    def test_numbering_extends_beyond_nine_columns(self) -> None:
        book = load_workbook(self.paths["source"])
        sheet = book.worksheets[0]
        sheet.unmerge_cells("G7:H7")
        sheet.merge_cells("G7:P7")
        sheet["Q7"] = "TK"
        for column in range(7, 18):
            sheet.cell(8, column, datetime(2026, 5, 1))
            sheet.cell(9, column, 1)
            sheet.cell(10, column, 0)
        sheet["Q6"] = None
        sheet["R6"] = None
        sheet["S6"] = "美国备注"
        sheet["T6"] = "TK备注"
        book.save(self.paths["source"])
        result = convert(self.paths)
        self.assertEqual(result.rows[-1].order_number, "JQ202604030411")
        self.assertEqual(len(result.to_preview()["batches"]), 11)
