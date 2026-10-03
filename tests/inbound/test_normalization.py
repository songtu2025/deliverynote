from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd
from openpyxl import Workbook

from delivery_note.excel_io import (
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
)
from delivery_note.inbound.normalization import normalize_self_operated_delivery_sheet


class InboundNormalizationTests(unittest.TestCase):
    def test_delivery_numbers_are_extracted_independently(self) -> None:
        sheet = pd.DataFrame(
            [
                {
                    "积加SKU": "SKU-A",
                    "实收数量": 20,
                    "站点": "US站",
                    "品牌": "SIMARI",
                    "交货单号": "LN2608179012",
                },
                {
                    "积加SKU": "SKU-A",
                    "实收数量": 30,
                    "站点": "US站",
                    "品牌": "SIMARI",
                    "交货单号": "LN2608179011",
                },
                {
                    "积加SKU": "SKU-B",
                    "实收数量": 10,
                    "站点": "US站",
                    "品牌": "SEEKWAY",
                    "交货单号": "单上没有，来货有",
                },
            ]
        )

        result = normalize_self_operated_delivery_sheet(sheet)

        self.assertEqual(
            result.delivery_lines.to_dict("records"),
            [
                {"SKU": "SKU-A", "原始站点": "US", "交货量": 50},
                {"SKU": "SKU-B", "原始站点": "US", "交货量": 10},
            ],
        )
        self.assertEqual(
            result.delivery_numbers,
            ("LN2608179011", "LN2608179012"),
        )
        self.assertEqual(result.invalid_delivery_values, ("单上没有，来货有",))

    def test_missing_received_quantity_is_rejected(self) -> None:
        sheet = pd.DataFrame(
            [
                {
                    "积加SKU": "SKU-A",
                    "实收数量": None,
                    "站点": "US站",
                    "交货单号": "LN2608179011",
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "实收数量存在空值或无效值"):
            normalize_self_operated_delivery_sheet(sheet)

    def test_excel_readers_load_detail_and_inbound_rows(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            delivery_path = root / "交货单.xlsx"
            delivery_book = Workbook()
            delivery_sheet = delivery_book.worksheets[0]
            delivery_sheet.title = "明细"
            delivery_sheet.append(["交货单标题"])
            delivery_sheet.append([])
            delivery_sheet.append(["说明"])
            delivery_sheet.append(["积加SKU", "实收数量", "站点", "交货单号"])
            delivery_sheet.append(["SKU-A", 20, "US站", "LN2608179011"])
            delivery_book.save(delivery_path)

            inbound_path = root / "自营仓.xlsx"
            inbound_book = Workbook()
            inbound_sheet = inbound_book.worksheets[0]
            inbound_sheet.append(
                [
                    "入库单号",
                    "入库仓",
                    "SKU",
                    "平台站点",
                    "关联交货单/调拨单",
                    "关联采购单",
                    "应收货",
                    "供应商",
                ]
            )
            inbound_sheet.append(
                [
                    "WV-1",
                    "水鞋-广州仓",
                    "SKU-A",
                    "AMAZON:RIVMOUNT:US",
                    "LN2608179011",
                    "PO2601010001",
                    30,
                    "Yu feng",
                ]
            )
            inbound_book.save(inbound_path)

            delivery = read_self_operated_delivery_workbook(delivery_path)
            inbound = read_self_operated_inbound_workbook(inbound_path)

        self.assertEqual(delivery.delivery_lines.iloc[0]["交货量"], 20)
        self.assertEqual(delivery.delivery_numbers, ("LN2608179011",))
        self.assertEqual(inbound.iloc[0]["应收货"], 30)
