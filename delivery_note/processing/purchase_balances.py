from dataclasses import dataclass

import pandas as pd

from ..config import PURCHASE_STATUSES, warehouse_sort_key
from .models import _require_columns


@dataclass
class _PurchaseBalance:
    destination_warehouse: object
    remaining: int | float


@dataclass
class PurchaseBalanceLedger:
    """保存单批次内按匹配键聚合且可扣减的采购余额。"""

    balances: dict[
        tuple[object, object, object],
        tuple[_PurchaseBalance, ...],
    ]

    def active_candidates(
        self,
        supplier: object,
        sku: object,
        site: object,
    ) -> tuple[_PurchaseBalance, ...]:
        """返回当前仍有余额的候选仓，并保持既定仓库顺序。"""

        return tuple(
            balance
            for balance in self.balances.get((supplier, sku, site), ())
            if balance.remaining > 0
        )


def build_purchase_balance_ledger(
    purchase_rows: pd.DataFrame,
) -> PurchaseBalanceLedger:
    """从不可变采购输入一次构建批次作用域的聚合余额账本。"""

    _require_columns(
        purchase_rows,
        {"单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"},
        "采购需求",
    )
    purchases = purchase_rows.loc[
        purchase_rows["单据状态"].isin(PURCHASE_STATUSES),
        ["SKU", "供应商", "平台站点", "目的仓", "未交量"],
    ].copy()
    purchases["未交量"] = pd.to_numeric(
        purchases["未交量"],
        errors="coerce",
    ).fillna(0)
    purchases = purchases[purchases["未交量"] > 0]
    needs = (
        purchases.groupby(
            ["SKU", "供应商", "平台站点", "目的仓"],
            as_index=False,
        )["未交量"]
        .sum()
        .reset_index(drop=True)
    )

    grouped: dict[
        tuple[object, object, object],
        list[_PurchaseBalance],
    ] = {}
    for sku, supplier, site, destination, quantity in needs.itertuples(
        index=False,
        name=None,
    ):
        grouped.setdefault((supplier, sku, site), []).append(
            _PurchaseBalance(destination, quantity)
        )
    for balances in grouped.values():
        balances.sort(
            key=lambda balance: warehouse_sort_key(str(balance.destination_warehouse))
        )
    return PurchaseBalanceLedger(
        {key: tuple(balances) for key, balances in grouped.items()}
    )
