from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook, load_workbook

import delivery_note.excel.templates as template_module
import delivery_note.inspection.workbooks as workbook_module
from delivery_note.inbound.models import INBOUND_TEMPLATE_COLUMNS
from delivery_note.input_inspection import (
    inspect_input_version,
    inspect_input_version_with_preview,
    preview_input_version,
    preview_input_version_page,
)
from delivery_note.processing.models import IMPORT_COLUMNS
from tests.support.excel import make_template_preview_workbook
from tests.support.inspection import InputInspectionCase


class InputInspectionTests(InputInspectionCase):
    def test_template_preview_and_pages_use_active_sheet(self) -> None:
        for kind, columns in (
            ("template", IMPORT_COLUMNS),
            ("inbound_template", INBOUND_TEMPLATE_COLUMNS),
        ):
            for active_index in (0, 1):
                for auxiliary_valid in (False, True):
                    with self.subTest(
                        kind=kind, index=active_index, valid=auxiliary_valid
                    ):
                        path = self.root / f"{kind}.xlsx"
                        workbook = make_template_preview_workbook(
                            kind, active_index, auxiliary_valid=auxiliary_valid
                        )
                        workbook.save(path)
                        summary = inspect_input_version(kind, path)
                        result = inspect_input_version_with_preview(kind, path, 0, 1)
                        page = preview_input_version_page(kind, path, 1, 1, summary)
                        self.assertEqual(summary, result["summary"])
                        self.assertEqual(summary["columns"], columns)
                        self.assertEqual(summary["row_count"], 2)
                        self.assertEqual(
                            result["preview"]["rows"][0][columns[0]], "活动示例"
                        )
                        self.assertEqual(page["rows"][0][columns[0]], "活动数据")
                        self.assertEqual(page["columns"], columns)
                        self.assertEqual(page["total"], 2)
                        self.assertIsNone(page["rows"][0][columns[-1]])
                        self.assertIsNone(page["rows"][0][columns[-2]])

    def test_template_inspection_rejects_invalid_active_sheet(self) -> None:
        for kind, header_row in (("template", 2), ("inbound_template", 1)):
            with self.subTest(kind=kind):
                path = self.root / f"{kind}.xlsx"
                workbook = make_template_preview_workbook(kind)
                workbook.worksheets[1].cell(row=header_row, column=1).value = "错误表头"
                workbook.save(path)
                with self.assertRaisesRegex(ValueError, "表头与预期字段不一致"):
                    inspect_input_version_with_preview(kind, path, 0, 1)

    def test_template_inspection_does_not_add_workbook_parses(self) -> None:
        for kind in ("template", "inbound_template"):
            with self.subTest(kind=kind):
                path = self.root / f"{kind}.xlsx"
                make_template_preview_workbook(kind).save(path)
                with (
                    patch.object(
                        template_module, "load_workbook", wraps=load_workbook
                    ) as load,
                    patch.object(
                        workbook_module.pd, "read_excel", wraps=pd.read_excel
                    ) as read,
                ):
                    inspect_input_version_with_preview(kind, path, 0, 1)
                self.assertEqual(load.call_count, 1)
                self.assertEqual(read.call_count, 1)
                self.assertEqual(read.call_args.kwargs.get("sheet_name"), "活动模板")

    def test_all_input_kinds_are_read_and_template_uses_second_row_headers(
        self,
    ) -> None:
        sources = {
            "purchase": pd.DataFrame(
                [["待交货", "KuangBiao", "SKU-A", "SEEKWAY:US", "广州仓", 10]],
                columns=["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"],
            ),
            "product": pd.DataFrame(
                [["SKU-A", "SEEKWAY:US", "水鞋", "锁"]],
                columns=["SKU", "店铺/站点", "品类A", "锁仓MKSU"],
            ),
            "supplier": pd.DataFrame(
                [["GYS-001", "KuangBiao", "启用"]],
                columns=["供应商编号", "供应商名称", "状态"],
            ),
        }
        for kind, frame in sources.items():
            with self.subTest(kind=kind):
                path = self.root / f"{kind}.xlsx"
                frame.to_excel(path, index=False)
                inspection = inspect_input_version(kind, path)
                self.assertEqual(inspection["row_count"], 1)
                expected_columns = list(frame.columns)
                if kind == "supplier":
                    expected_columns.append("供应商别名")
                self.assertEqual(inspection["columns"], expected_columns)
                preview = preview_input_version(kind, path, offset=0, limit=10)
                self.assertEqual(
                    preview["rows"][0][frame.columns[-1]], frame.iloc[0, -1]
                )

        template_path = self.root / "template.xlsx"
        workbook = Workbook()
        sheet = workbook.worksheets[0]
        sheet["A1"] = "模板提示"
        sheet.append(IMPORT_COLUMNS)
        sheet.append(["广州仓", "GYS-001", "SKU-A", 10, "SEEKWAY:US", None, None])
        workbook.save(template_path)

        inspection = inspect_input_version("template", template_path)
        preview = preview_input_version("template", template_path, offset=0, limit=10)
        self.assertEqual(inspection["columns"], IMPORT_COLUMNS)
        self.assertEqual(inspection["row_count"], 1)
        self.assertEqual(preview["rows"][0]["*本次交货量"], 10)
        self.assertIsNone(preview["rows"][0]["单据备注"])

    def test_supplier_inspection_reports_alias_metrics_and_conflicts(self) -> None:
        path = self.root / "supplier-aliases.xlsx"
        pd.DataFrame(
            [
                ["GYS-1", "Alpha", "启用", " A-One | shared "],
                ["GYS-2", "Beta", "启用", "shared-shop|B-One"],
            ],
            columns=["供应商编号", "供应商名称", "状态", "供应商别名"],
        ).to_excel(path, index=False)

        inspection = inspect_input_version("supplier", path)

        self.assertEqual(
            inspection["metrics"],
            {"aliases": 4, "suppliers_with_aliases": 2},
        )
        self.assertEqual(inspection["issues"][0]["row_numbers"], [2, 3])
        self.assertEqual(
            inspection["issues"][0]["code"],
            "supplier_identifier_conflict",
        )

    def test_unknown_input_kind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的输入资料类型"):
            inspect_input_version("other", self.path)
