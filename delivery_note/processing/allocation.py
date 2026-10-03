from dataclasses import dataclass, field
from typing import MutableMapping

import pandas as pd

from ..exception_reasons import ExceptionReason
from .keys import make_overreceipt_key
from .models import OVERRECEIPT_NOTE_PREFIX, OverreceiptAllowance, OverreceiptKey
from .purchase_balances import PurchaseBalanceLedger, _PurchaseBalance


@dataclass
class AllocationSummary:
    """单条交货的正常、超收和待处理数量。"""

    remaining: int
    purchase: int = 0
    overreceipt: int = 0
    destination: object = ""

    @property
    def allocated(self) -> int:
        return self.purchase + self.overreceipt


@dataclass
class DeliveryAllocator:
    """按既定仓库顺序扣减共享余额，保留每一条交货数量。"""

    supplier_name: str
    supplier_code: str
    ledger: PurchaseBalanceLedger
    allowances: MutableMapping[OverreceiptKey, OverreceiptAllowance] | None
    import_rows: list[dict] = field(default_factory=list, init=False)
    exceptions: list[dict] = field(default_factory=list, init=False)
    candidates: dict[tuple[object, object], tuple[_PurchaseBalance, ...]] = field(
        default_factory=dict, init=False
    )

    def _import_row(
        self, row: pd.Series, destination: object, quantity: int, note: str = ""
    ) -> dict:
        return {
            "*目的仓": destination,
            "*供应商编码": self.supplier_code,
            "*SKU": row["SKU"],
            "*本次交货量": quantity,
            "*站点": row["完整站点"],
            "单据备注": "",
            "交货备注": note,
        }

    def _pending_row(
        self,
        row: pd.Series,
        summary: AllocationSummary,
        reason: str,
        allowance: OverreceiptAllowance | None = None,
    ) -> dict:
        return {
            "SKU": row["SKU"],
            "原始站点": row["原始站点"],
            "完整站点": row["完整站点"] or "",
            "目的仓": summary.destination or "",
            "交货量": int(row["交货量"]),
            "已自动分配量": summary.allocated,
            "人工处理量": summary.remaining,
            "异常原因": reason,
            "正常采购分配量": summary.purchase,
            "超收规则分配量": summary.overreceipt,
            "超收剩余额度": allowance.remaining if allowance is not None else None,
        }

    def _allocate_purchase(
        self,
        row: pd.Series,
        balances: tuple[_PurchaseBalance, ...],
        summary: AllocationSummary,
    ) -> None:
        for balance in balances:
            quantity = min(summary.remaining, int(balance.remaining))
            if quantity <= 0:
                continue
            self.import_rows.append(
                self._import_row(row, balance.destination_warehouse, quantity)
            )
            balance.remaining -= quantity
            summary.remaining -= quantity
            summary.purchase += quantity
            summary.destination = balance.destination_warehouse
            if summary.remaining == 0:
                break

    def _allocate_overreceipt(
        self,
        row: pd.Series,
        summary: AllocationSummary,
        allowance: OverreceiptAllowance | None,
    ) -> None:
        if summary.remaining <= 0 or allowance is None or allowance.remaining <= 0:
            return
        quantity = min(summary.remaining, allowance.remaining)
        self.import_rows.append(
            self._import_row(
                row,
                allowance.destination_warehouse,
                quantity,
                f"{OVERRECEIPT_NOTE_PREFIX}：{quantity}",
            )
        )
        allowance.remaining -= quantity
        summary.remaining -= quantity
        summary.overreceipt += quantity
        summary.destination = allowance.destination_warehouse

    def allocate(self, row: pd.Series) -> None:
        summary = AllocationSummary(remaining=int(row["交货量"]))
        if row["异常原因"]:
            self.exceptions.append(self._pending_row(row, summary, row["异常原因"]))
            return

        key = (row["SKU"], row["完整站点"])
        if key not in self.candidates:
            self.candidates[key] = self.ledger.active_candidates(
                self.supplier_name, row["SKU"], row["完整站点"]
            )
        balances = self.candidates[key]
        self._allocate_purchase(row, balances, summary)
        allowance_key = make_overreceipt_key(
            self.supplier_name, row["SKU"], row["完整站点"]
        )
        allowance = (
            self.allowances.get(allowance_key) if self.allowances is not None else None
        )
        self._allocate_overreceipt(row, summary, allowance)
        if summary.remaining <= 0:
            return

        reason = (
            ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED
            if allowance is not None
            else ExceptionReason.PURCHASE_BALANCE_EXCEEDED
            if balances
            else ExceptionReason.PURCHASE_NOT_FOUND
        )
        if summary.allocated > 0 and allowance is None:
            self.import_rows[-1]["交货备注"] = f"{reason}：{summary.remaining}"
        self.exceptions.append(self._pending_row(row, summary, reason, allowance))
