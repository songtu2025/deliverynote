"""检查自营仓 A:T 内容、示例样式及单文件和压缩包契约。"""

from io import BytesIO
from pathlib import Path
from typing import Any
import unittest
from zipfile import ZipFile

from openpyxl import load_workbook

from delivery_note.inbound.models import INBOUND_TEMPLATE_COLUMNS


def assert_inbound_exports(case: unittest.TestCase, record: dict[str, Any]) -> None:
    batch = record["batch"]
    site = "AMAZON:RIVMOUNT:US" if batch["site_resolutions"] else "AMAZON:SEEKWAY:US"
    for source in batch["files"]:
        data = record["exports"][source["original_name"]]
        workbook = load_workbook(BytesIO(data), data_only=True)
        sheet = workbook["批量入库"]
        case.assertEqual([cell.value for cell in sheet[1]], INBOUND_TEMPLATE_COLUMNS)
        case.assertEqual(
            sum(sheet.cell(row, 17).value for row in range(2, sheet.max_row + 1)),
            source["import_total"],
        )
        for index, row in enumerate(sheet.iter_rows(min_row=2), start=2):
            case.assertEqual(row[7].value, site)
            case.assertEqual(row[11].value, 10)
            case.assertEqual(row[17].value, "未分配库位")
            case.assertIsNone(row[18].value)
            for cell in row:
                case.assertEqual(cell.font.name, "宋体")
                case.assertEqual(cell.font.sz, 10)
                case.assertEqual(cell.fill.fgColor.rgb, "00FFF2CC")
                case.assertEqual(cell.number_format, "0")
            case.assertEqual(sheet.row_dimensions[index].height, 26)
        if source["manual_total"]:
            case.assertIn(
                "规则允许超收：5",
                [sheet.cell(row, 20).value for row in range(2, sheet.max_row + 1)],
            )
        workbook.close()
    if len(batch["files"]) == 1:
        case.assertEqual(record["download"], next(iter(record["exports"].values())))
        case.assertIsNone(record["merged"])
        return
    with ZipFile(BytesIO(record["download"])) as archive:
        expected = {
            Path(name).stem + "_积加入库.xlsx": data
            for name, data in record["exports"].items()
        }
        case.assertEqual(set(archive.namelist()), set(expected))
        for name, data in expected.items():
            case.assertEqual(archive.read(name), data)
    workbook = load_workbook(BytesIO(record["merged"]), data_only=True)
    sheet = workbook["批量入库"]
    case.assertEqual(sheet.max_row, 2)
    case.assertEqual(sheet.cell(2, 17).value, 15)
    workbook.close()
