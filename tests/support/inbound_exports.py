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
        assert_inbound_workbook(
            case, data, site, source["import_total"], bool(source["manual_total"])
        )
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
    assert_inbound_workbook(case, record["merged"], site, 15, True)


def assert_inbound_workbook(
    case: unittest.TestCase, data: bytes, site: str, total: int, overreceipt: bool
) -> None:
    workbook = load_workbook(BytesIO(data), data_only=True)
    sheet = workbook["批量入库"]
    case.assertEqual([cell.value for cell in sheet[1]], INBOUND_TEMPLATE_COLUMNS)
    case.assertEqual(sheet.max_row, 2)
    expected = {
        1: "IN-R" if site == "AMAZON:RIVMOUNT:US" else "IN-S",
        3: "自营仓",
        5: "SKU-A",
        8: site,
        9: f"PO-20260801-{site}",
        10: "LN2608179025",
        12: 10,
        17: total,
        18: "未分配库位",
        19: None,
        20: "规则允许超收：5" if overreceipt else None,
    }
    for column, value in expected.items():
        case.assertEqual(sheet.cell(2, column).value, value)
    for cell in sheet[2]:
        case.assertEqual(cell.font.name, "宋体")
        case.assertEqual(cell.font.sz, 10)
        case.assertEqual(cell.fill.fgColor.rgb, "00FFF2CC")
        case.assertEqual(cell.number_format, "0")
        case.assertEqual(cell.alignment.horizontal, "center")
        case.assertEqual(cell.alignment.vertical, "center")
        case.assertTrue(cell.alignment.wrap_text)
        for name in ("left", "right", "top", "bottom"):
            case.assertEqual(getattr(cell.border, name).style, "thin")
    case.assertEqual(sheet.row_dimensions[2].height, 26)
    workbook.close()
