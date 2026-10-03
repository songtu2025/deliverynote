from typing import Any

import pandas as pd

from tests.support.allocation import AllocationCase


class InboundAllocationCase(AllocationCase):
    product_site = "RIVMOUNT:US"

    @staticmethod
    def inbound(rows: list[dict[str, Any]]) -> pd.DataFrame:
        defaults = {
            "入库单号": "WV-1",
            "入库仓": "水鞋-广州仓",
            "SKU": "SKU-A",
            "平台站点": "AMAZON:RIVMOUNT:US",
            "关联交货单/调拨单": "LN2608179011",
            "关联采购单": "PO2601010001",
            "应收货": 100,
            "供应商": "Yu feng",
        }
        return pd.DataFrame([{**defaults, **row} for row in rows])
