import unittest
import pandas as pd
from delivery_note.processing.pending import (
    build_manual_import_rows,
)


class ManualImportMappingTests(unittest.TestCase):
    def test_excess_quantity_maps_to_official_import_columns(self):
        exceptions = pd.DataFrame(
            [
                [
                    "SKU-A",
                    "US",
                    "AMAZON:SEEKWAY:US",
                    "水鞋-广州仓",
                    120,
                    80,
                    40,
                    "超出采购未交量",
                ]
            ],
            columns=[
                "SKU",
                "原始站点",
                "完整站点",
                "目的仓",
                "交货量",
                "已自动分配量",
                "人工处理量",
                "异常原因",
            ],
        )

        result = build_manual_import_rows(exceptions, "KuangBiao")

        self.assertEqual(
            result.to_dict("records"),
            [
                {
                    "*目的仓": "水鞋-广州仓",
                    "*供应商编码": "KuangBiao",
                    "*SKU": "SKU-A",
                    "*本次交货量": 40,
                    "*站点": "AMAZON:SEEKWAY:US",
                    "单据备注": "",
                    "交货备注": "超出采购未交量：40",
                }
            ],
        )

    def test_missing_or_ambiguous_site_stays_blank(self):
        exceptions = pd.DataFrame(
            [
                ["SKU-A", "US", "", "", 20, 0, 20, "产品信息未匹配"],
                [
                    "SKU-B",
                    "US",
                    "AMAZON:OTHER:US、AMAZON:SEEKWAY:US",
                    "",
                    30,
                    0,
                    30,
                    "产品信息站点不唯一",
                ],
            ],
            columns=[
                "SKU",
                "原始站点",
                "完整站点",
                "目的仓",
                "交货量",
                "已自动分配量",
                "人工处理量",
                "异常原因",
            ],
        )

        result = build_manual_import_rows(exceptions, "KuangBiao")

        self.assertEqual(result["*站点"].tolist(), ["", ""])
        self.assertEqual(result["*目的仓"].tolist(), ["", ""])
        self.assertEqual(
            result["交货备注"].tolist(),
            [
                "产品信息未匹配；原始站点：US",
                "产品信息站点不唯一：AMAZON:OTHER:US、AMAZON:SEEKWAY:US",
            ],
        )
