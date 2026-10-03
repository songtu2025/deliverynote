from dataclasses import dataclass
from typing import Sequence

import pandas as pd


SOURCE_COLUMNS = {"积加SKU", "实收数量", "站点", "交货单号"}
INBOUND_COLUMNS = {
    "入库单号",
    "入库仓",
    "SKU",
    "平台站点",
    "关联交货单/调拨单",
    "关联采购单",
    "应收货",
    "供应商",
}
ALLOCATION_COLUMNS = [
    "正常分配数量",
    "规则内超收数量",
    "本次入库",
    "入库库位",
    "本次退货",
    "超过超收规则数量",
    "超收原因",
]
INBOUND_TEMPLATE_COLUMNS = [
    "入库单号",
    "发货单号",
    "入库仓",
    "产品名称",
    "SKU",
    "MSKU",
    "FNSKU",
    "平台站点",
    "关联采购单",
    "关联交货单/调拨单",
    "关联质检单",
    "应收货",
    "最大可收货",
    "已收货",
    "已入库",
    "已退货",
    "本次入库",
    "入库库位",
    "本次退货",
    "超收原因",
]
PENDING_COLUMNS = [
    "供应商",
    "SKU",
    "原始站点",
    "完整站点",
    "质检合格数量",
    "正常分配数量",
    "规则内超收数量",
    "超过超收规则数量",
    "待处理数量",
    "待处理原因",
]


@dataclass(frozen=True)
class SelfOperatedDeliverySource:
    delivery_lines: pd.DataFrame
    delivery_numbers: tuple[str, ...]
    invalid_delivery_values: tuple[str, ...]


@dataclass(frozen=True)
class SelfOperatedInboundResult:
    allocation_rows: pd.DataFrame
    pending_rows: pd.DataFrame
    qualified_total: int
    import_total: int
    pending_total: int


@dataclass(frozen=True)
class SelfOperatedInboundRequest:
    """批次中按用户顺序排列的一份质检交货单。"""

    source_id: str | int
    delivery_lines: pd.DataFrame
    delivery_numbers: Sequence[str]
    supplier_name: str


@dataclass(frozen=True)
class SelfOperatedInboundItemResult:
    source_id: str | int
    file_order: int
    delivery_numbers: tuple[str, ...]
    supplier_name: str
    result: SelfOperatedInboundResult


@dataclass(frozen=True)
class SelfOperatedInboundBatchResult:
    items: tuple[SelfOperatedInboundItemResult, ...]
    qualified_total: int
    import_total: int
    pending_total: int
