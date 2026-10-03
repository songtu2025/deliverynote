from dataclasses import dataclass

import pandas as pd


IMPORT_COLUMNS = [
    "*目的仓",
    "*供应商编码",
    "*SKU",
    "*本次交货量",
    "*站点",
    "单据备注",
    "交货备注",
]

POSITION_VALUE_COLUMNS = [
    "规模定位",
    "备货定位",
]
POSITION_SOURCE_COLUMNS = [
    "店铺-站点",
    "积加SKU",
    "MSKU",
    *POSITION_VALUE_COLUMNS,
]
PENDING_COLUMNS = [*IMPORT_COLUMNS, *POSITION_VALUE_COLUMNS]

EXCEPTION_COLUMNS = [
    "SKU",
    "原始站点",
    "完整站点",
    "目的仓",
    "交货量",
    "已自动分配量",
    "人工处理量",
    "异常原因",
]
EXCEPTION_GUIDANCE_COLUMNS = [
    "正常采购分配量",
    "超收规则分配量",
    "超收剩余额度",
]
RESULT_EXCEPTION_COLUMNS = [*EXCEPTION_COLUMNS, *EXCEPTION_GUIDANCE_COLUMNS]

OVERRECEIPT_NOTE_PREFIX = "规则允许超收"
OverreceiptKey = tuple[str, str, str]


@dataclass(frozen=True)
class BatchResult:
    import_rows: pd.DataFrame
    exception_rows: pd.DataFrame
    delivery_total: int
    import_total: int
    manual_total: int


@dataclass(frozen=True)
class OverreceiptPolicy:
    short_tail_limit: int
    medium_tail_limit: int
    long_tail_limit: int
    allowed_warehouses: frozenset[str]

    def __post_init__(self) -> None:
        limits = (
            self.short_tail_limit,
            self.medium_tail_limit,
            self.long_tail_limit,
        )
        if any(
            isinstance(limit, bool) or not isinstance(limit, int) for limit in limits
        ):
            raise ValueError("超收数量必须是整数")
        if any(limit < 0 for limit in limits):
            raise ValueError("超收数量不能小于 0")
        warehouses = frozenset(
            str(warehouse).strip()
            for warehouse in self.allowed_warehouses
            if str(warehouse).strip()
        )
        object.__setattr__(self, "allowed_warehouses", warehouses)

    def limit_for(self, scale: str) -> int:
        return {
            "短尾": self.short_tail_limit,
            "中尾": self.medium_tail_limit,
            "长尾": self.long_tail_limit,
        }.get(scale, 0)


@dataclass
class OverreceiptAllowance:
    remaining: int
    destination_warehouse: str


def _require_columns(frame: pd.DataFrame, required: set[str], source: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{source}缺少必要字段：{', '.join(missing)}")
