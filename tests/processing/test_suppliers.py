from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import pandas as pd
from delivery_note.config import (
    SupplierIdentity,
    resolve_supplier,
    validate_supplier_frame,
)
from delivery_note.config import build_document_note


class SupplierConfigTests(unittest.TestCase):
    def test_resolve_supplier_from_delivery_filename(self):

        supplier_rows = pd.DataFrame(
            [
                {"供应商编号": "GYS-023", "供应商名称": "KuangBiao", "状态": "启用"},
                {"供应商编号": "GYS-027", "供应商名称": "Zhangdun", "状态": "启用"},
            ]
        )
        supplier = resolve_supplier(
            Path("260628 掌盾-SIMARI交货单.xlsx"), supplier_rows
        )

        self.assertEqual(supplier, SupplierIdentity(name="Zhangdun", code="GYS-027"))

    def test_build_document_note_generates_stable_group_sequence(self):

        supplier_rows = pd.DataFrame(
            [
                {"供应商编号": "GYS-023", "供应商名称": "KuangBiao", "状态": "启用"},
                {"供应商编号": "GYS-026", "供应商名称": "Yu feng", "状态": "启用"},
            ]
        )
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            first = directory_path / "260717-狂飙-A产品交货单-发货96箱.xlsx"
            second = directory_path / "260717-狂飙-B产品交货单-发货86箱.xlsx"
            other_supplier = directory_path / "260717 裕枫SEEKWAY交货单-交货151箱.xls"
            for path in (first, second, other_supplier):
                path.touch()

            first_note = build_document_note(first, supplier_rows)
            second_note = build_document_note(second, supplier_rows)
            other_note = build_document_note(other_supplier, supplier_rows)

        self.assertEqual(first_note, "260717-狂飙-01-96箱")
        self.assertEqual(second_note, "260717-狂飙-02-86箱")
        self.assertEqual(other_note, "260717-裕枫-01-151箱")

    def test_unknown_supplier_filename_is_rejected(self):

        supplier_rows = pd.DataFrame(
            [{"供应商编号": "GYS-023", "供应商名称": "KuangBiao", "状态": "启用"}]
        )
        with self.assertRaisesRegex(ValueError, "无法从文件名识别供应商"):
            resolve_supplier(Path("未知供应商交货单.xlsx"), supplier_rows)

    def test_resolve_supplier_uses_chinese_and_english_aliases_once(self):
        supplier_rows = pd.DataFrame(
            [
                {
                    "供应商编号": "STGYS001",
                    "供应商名称": "RUIZY",
                    "状态": "启用",
                    "供应商别名": " 瑞智雅 | RIVBOS || ",
                }
            ]
        )

        chinese = resolve_supplier(Path("260903-瑞智雅眼镜交货单.xlsx"), supplier_rows)
        english = resolve_supplier(Path("260903-RIVBOS眼镜交货单.xlsx"), supplier_rows)
        combined = resolve_supplier(
            Path("260903-瑞智雅RIVBOS眼镜交货单-发货53箱 (1).xlsx"),
            supplier_rows,
        )

        expected = SupplierIdentity(name="RUIZY", code="STGYS001")
        self.assertEqual(chinese, expected)
        self.assertEqual(english, expected)
        self.assertEqual(combined, expected)

    def test_multiple_supplier_matches_are_reported_clearly(self):
        supplier_rows = pd.DataFrame(
            [
                {
                    "供应商编号": "GYS-1",
                    "供应商名称": "Alpha",
                    "状态": "启用",
                    "供应商别名": "RIV",
                },
                {
                    "供应商编号": "GYS-2",
                    "供应商名称": "Beta",
                    "状态": "启用",
                    "供应商别名": "RIVBOS",
                },
            ]
        )

        with self.assertRaisesRegex(ValueError, "匹配到多个供应商.*Alpha.*Beta"):
            resolve_supplier(Path("260903-RIVBOS交货单.xlsx"), supplier_rows)

    def test_supplier_conflict_validation_reports_excel_rows(self):
        supplier_rows = pd.DataFrame(
            [
                ["GYS-1", "瑞智", "启用", "RIV"],
                ["GYS-2", "瑞智雅", "启用", "RIVBOS"],
                ["GYS-3", "Disabled", "停用", "RIVBOS-US"],
            ],
            columns=["供应商编号", "供应商名称", "状态", "供应商别名"],
        )

        issues = validate_supplier_frame(supplier_rows)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "supplier_identifier_conflict")
        self.assertEqual(issues[0]["row_numbers"], [2, 3])
