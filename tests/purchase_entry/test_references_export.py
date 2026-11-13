"""资料读取与采购导出的字段、样式和隐私边界。"""

from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from tests.purchase_entry.support import convert, make_files


class PurchaseReferenceExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = make_files(Path(self.directory.name))

    def test_auxiliary_sparse_warehouse_columns_still_supported(self) -> None:
        from delivery_note.purchase_entry import (
            read_warehouse_frame,
            validate_warehouses,
        )

        book = Workbook()
        sheet = book.worksheets[0]
        sheet.title = "辅助计算"
        sheet["O1"], sheet["P1"] = "SKU", "仓库"
        sheet["O2"], sheet["P2"] = "SKU-A", "普通仓"
        sheet.cell(1048576, 5).number_format = "0"
        book.save(self.paths["warehouse"])
        validate_warehouses(self.paths["warehouse"])
        self.assertEqual(len(read_warehouse_frame(self.paths["warehouse"])), 1)
        self.assertEqual(convert(self.paths).rows[0].msku, "MSKU-A")

    def test_incomplete_records_block_only_when_matched(self) -> None:
        from delivery_note.purchase_entry import read_purchase_products

        book = load_workbook(self.paths["product"])
        book.worksheets[0].append(["US", None, "旧店铺", "旧MSKU", "合成品类", ""])
        book.worksheets[0]["D3"] = None
        book.save(self.paths["product"])
        self.assertEqual(len(read_purchase_products(self.paths["product"])), 3)
        self.assertEqual(convert(self.paths).row_count, 3)
        book.worksheets[0]["D2"] = None
        book.save(self.paths["product"])
        with self.assertRaisesRegex(ValueError, "G9.*SKU-A.*MSKU"):
            convert(self.paths)

    def test_product_headers_can_move_and_keep_text_msku(self) -> None:
        from delivery_note.purchase_entry import read_purchase_products

        book = Workbook()
        sheet = book.worksheets[0]
        sheet.append(["备注", "MSKU", "品类A", "国家", "店铺/站点", "锁仓MKSU", "SKU"])
        sheet.append(["合成", "00123", "合成品类", "美国站", "店铺/US", "", "SKU-A"])
        book.save(self.paths["product"])
        frame = read_purchase_products(self.paths["product"])
        self.assertEqual(list(frame.columns), ["国家", "SKU", "店铺/站点", "MSKU"])
        self.assertEqual(frame.iloc[0]["国家"], "US")
        self.assertEqual(convert(self.paths).rows[0].msku, "00123")

    def test_purchase_requires_additional_product_columns(self) -> None:
        for column, label in ((1, "国家"), (4, "MSKU")):
            with self.subTest(label=label):
                self.paths = make_files(Path(self.directory.name))
                book = load_workbook(self.paths["product"])
                book.worksheets[0].delete_cols(column)
                book.save(self.paths["product"])
                with self.assertRaisesRegex(ValueError, f"商品信息.*{label}"):
                    convert(self.paths)

    def test_product_country_matches_chinese_or_code_and_deduplicates(self) -> None:
        book = load_workbook(self.paths["product"])
        sheet = book.worksheets[0]
        sheet["A2"] = "美国"
        book.save(self.paths["product"])
        self.assertEqual(convert(self.paths).rows[0].msku, "MSKU-A")
        sheet.append(["us", "SKU-A", "店铺/US", "MSKU-A", "其他品类", "其他锁仓"])
        book.save(self.paths["product"])
        self.assertEqual(convert(self.paths).rows[0].msku, "MSKU-A")

    def test_literal_na_msku_is_text_and_empty_msku_is_rejected(self) -> None:
        book = load_workbook(self.paths["product"])
        book.worksheets[0]["D2"] = "NA"
        book.save(self.paths["product"])
        self.assertEqual(convert(self.paths).rows[0].msku, "NA")
        book.worksheets[0]["D2"] = None
        book.save(self.paths["product"])
        with self.assertRaisesRegex(ValueError, "G9.*SKU-A.*MSKU"):
            convert(self.paths)

    def test_validations_reject_missing_headers(self) -> None:
        from delivery_note.purchase_entry import validate_warehouses

        book = load_workbook(self.paths["warehouse"])
        book.worksheets[0]["B1"] = "错误"
        book.save(self.paths["warehouse"])
        with self.assertRaisesRegex(ValueError, "仓库"):
            validate_warehouses(self.paths["warehouse"])

    def test_empty_template_is_a_readable_validation_error(self) -> None:
        from delivery_note.purchase_entry import validate_template

        book = Workbook()
        book.worksheets[0].title = "采购单录入模板"
        book.save(self.paths["template"])
        with self.assertRaisesRegex(ValueError, "第2行"):
            validate_template(self.paths["template"])

    def test_template_validation_returns_headers_without_private_example(self) -> None:
        from delivery_note.purchase_entry import read_template_frame, validate_template

        validate_template(self.paths["template"])
        frame = read_template_frame(self.paths["template"])
        self.assertEqual(len(frame), 0)
        self.assertIn("供应商（编码）", frame.columns)
        book = load_workbook(self.paths["template"])
        book.worksheets[0]["P2"] = "无效字段"
        book.save(self.paths["template"])
        with self.assertRaisesRegex(ValueError, "采购量"):
            validate_template(self.paths["template"])

    def test_merged_export_removes_examples_sheets_and_fills_only_contract(
        self,
    ) -> None:
        from delivery_note.purchase_entry import export_purchase

        payload = export_purchase(convert(self.paths), self.paths["template"], "merged")
        book = load_workbook(BytesIO(payload))
        self.assertEqual(book.sheetnames, ["采购单录入模板"])
        sheet = book.worksheets[0]
        self.assertTrue(sheet["A1"].font.bold)
        self.assertEqual(sheet["A2"].value, "供应商（编码）")
        self.assertEqual(sheet.max_row, 5)
        self.assertEqual(sheet["A3"].value, "SUP001")
        self.assertEqual(sheet["B3"].value, "FKTJ0004")
        self.assertEqual(sheet["E3"].value, "CNY")
        self.assertEqual(sheet["G3"].value, "JQ202604030401")
        self.assertEqual(sheet["I3"].value, "美国备注")
        self.assertEqual(sheet["J3"].value, "普通仓")
        self.assertEqual(sheet["L3"].value, "AMAZON:店铺/US")
        self.assertEqual(sheet["N3"].value, "MSKU-A")
        self.assertEqual(sheet["O3"].value, "国内快递")
        self.assertEqual(sheet["P3"].value, 10)
        self.assertEqual(sheet["S3"].value, 1.25)
        self.assertEqual(sheet["V3"].value, datetime(2026, 5, 1))
        for column in (3, 4, 6, 8, 11, 13, 17, 18, 20, 21):
            self.assertIsNone(sheet.cell(3, column).value)

    def test_split_export_groups_by_order_number_not_date(self) -> None:
        from delivery_note.purchase_entry import export_purchase

        result = convert(self.paths)
        payload = export_purchase(result, self.paths["template"], "split")
        with ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(
                archive.namelist(),
                [
                    "JQ202604030401.xlsx",
                    "JQ202604030403.xlsx",
                ],
            )
            book = load_workbook(BytesIO(archive.read(archive.namelist()[1])))
            self.assertEqual(book.worksheets[0].max_row, 4)
        with self.assertRaisesRegex(ValueError, "导出模式"):
            export_purchase(result, self.paths["template"], "bad")

    def test_header_dimensions_register_styles_in_new_workbook(self) -> None:
        from delivery_note.purchase_entry import export_purchase

        template = load_workbook(self.paths["template"])
        sheet = template.worksheets[0]
        sheet.column_dimensions["J"].font = Font(name="宋体", color="FF0000")
        sheet.column_dimensions["J"].width = 25
        sheet.row_dimensions[2].fill = PatternFill("solid", fgColor="EEEEEE")
        sheet.row_dimensions[2].height = 32
        template.save(self.paths["template"])
        payload = export_purchase(convert(self.paths), self.paths["template"], "merged")
        output = load_workbook(BytesIO(payload))
        self.assertEqual(output.worksheets[0].column_dimensions["J"].width, 25)
        self.assertEqual(output.worksheets[0].column_dimensions["J"].font.name, "宋体")
        self.assertEqual(output.worksheets[0].row_dimensions[2].height, 32)
        self.assertEqual(
            output.worksheets[0].row_dimensions[2].fill.fgColor.rgb, "00EEEEEE"
        )
