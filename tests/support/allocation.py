import unittest

import pandas as pd

from delivery_note.processing.models import OverreceiptPolicy
from delivery_note.processing.overreceipt import build_overreceipt_allowances


class AllocationCase(unittest.TestCase):
    @staticmethod
    def delivery(quantity=100):
        return pd.DataFrame([{"SKU": "SKU-A", "原始站点": "US", "交货量": quantity}])

    @staticmethod
    def products(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "SKU": "SKU-A",
                    "店铺/站点": "SEEKWAY:US",
                    "品类A": "水鞋",
                    "锁仓MKSU": "锁",
                }
            ]
        )

    @staticmethod
    def purchases(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "单据状态": "待交货",
                    "供应商": "KuangBiao",
                    "SKU": "SKU-A",
                    "平台站点": "AMAZON:SEEKWAY:US",
                    "目的仓": "水鞋-广州仓",
                    "未交量": 150,
                }
            ]
        )

    @staticmethod
    def positions(rows=None):
        return pd.DataFrame(
            rows
            or [
                {
                    "店铺-站点": "SEEKWAY:US",
                    "积加SKU": "SKU-A",
                    "MSKU": "MSKU-A",
                    "规模定位": "短尾",
                    "备货定位": "备货",
                    "已下单可售天数": 30,
                }
            ]
        )

    @staticmethod
    def overreceipt_policy(allowed_warehouses=None):
        return OverreceiptPolicy(
            short_tail_limit=50,
            medium_tail_limit=20,
            long_tail_limit=10,
            allowed_warehouses=frozenset(allowed_warehouses or {"水鞋-广州仓"}),
        )

    def overreceipt_allowances(
        self,
        purchases=None,
        positions=None,
        allowed_warehouses=None,
    ):
        return build_overreceipt_allowances(
            purchases if purchases is not None else self.purchases(),
            positions if positions is not None else self.positions(),
            self.overreceipt_policy(allowed_warehouses),
        )
