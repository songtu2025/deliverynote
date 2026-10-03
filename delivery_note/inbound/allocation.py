from dataclasses import dataclass, field
from typing import Any, MutableMapping, cast

import pandas as pd

from ..exception_reasons import ExceptionReason
from ..processing.allocation import AllocationSummary
from ..processing.keys import make_overreceipt_key
from ..processing.models import OverreceiptAllowance, OverreceiptKey
from .models import ALLOCATION_COLUMNS, PENDING_COLUMNS, SelfOperatedInboundResult


@dataclass
class InboundAllocator:
    """扣减批次共享余额，并按来源行累计入库和待处理数量。"""

    supplier_name: str
    source_columns: list[str]
    balances: MutableMapping[int, int] | None
    allowances: MutableMapping[OverreceiptKey, OverreceiptAllowance] | None
    overreceipt_limit: int | None
    records: dict[int, dict[str, Any]] = field(default_factory=dict, init=False)
    pending: list[dict[str, Any]] = field(default_factory=list, init=False)
    generated_allowances: dict[OverreceiptKey, OverreceiptAllowance] = field(
        default_factory=dict, init=False
    )

    def _record(self, index: int, row: pd.Series) -> dict[str, Any]:
        record = {column: row[column] for column in self.source_columns}
        record.update(
            {
                "正常分配数量": 0,
                "规则内超收数量": 0,
                "本次入库": 0,
                "入库库位": "未分配库位",
                "本次退货": pd.NA,
                "超过超收规则数量": 0,
                "超收原因": "",
            }
        )
        return self.records.setdefault(index, record)

    def add_pending(
        self,
        row: pd.Series,
        summary: AllocationSummary,
        reason: str,
        over_limit: int = 0,
    ) -> None:
        self.pending.append(
            {
                "供应商": self.supplier_name,
                "SKU": row["SKU"],
                "原始站点": row["原始站点"],
                "完整站点": row["完整站点"],
                "质检合格数量": int(row["交货量"]),
                "正常分配数量": summary.purchase,
                "规则内超收数量": summary.overreceipt,
                "超过超收规则数量": over_limit,
                "待处理数量": summary.remaining,
                "待处理原因": reason,
            }
        )

    def _allocate_normal(
        self, candidates: pd.DataFrame, summary: AllocationSummary
    ) -> None:
        for source_order, candidate in candidates.iterrows():
            index = int(cast(int, source_order))
            available = int(candidate["_receivable"])
            if self.balances is not None:
                available = self.balances.setdefault(index, available)
            quantity = min(summary.remaining, available)
            if quantity <= 0:
                continue
            record = self._record(index, candidate)
            record["正常分配数量"] += quantity
            record["本次入库"] += quantity
            summary.purchase += quantity
            summary.remaining -= quantity
            if self.balances is not None:
                self.balances[index] = available - quantity
            if summary.remaining == 0:
                break

    def _allowance(self, row: pd.Series) -> OverreceiptAllowance | None:
        key = make_overreceipt_key(self.supplier_name, row["SKU"], row["完整站点"])
        allowances = (
            self.allowances
            if self.allowances is not None
            else self.generated_allowances
        )
        allowance = allowances.get(key)
        if allowance is None and self.overreceipt_limit is not None:
            allowance = allowances.setdefault(
                key, OverreceiptAllowance(self.overreceipt_limit, "")
            )
        return allowance

    def _allocate_overreceipt(
        self,
        candidates: pd.DataFrame,
        summary: AllocationSummary,
        allowance: OverreceiptAllowance | None,
    ) -> None:
        if summary.remaining <= 0 or allowance is None or allowance.remaining <= 0:
            return
        quantity = min(summary.remaining, allowance.remaining)
        record = self._record(int(candidates.index[-1]), candidates.iloc[-1])
        record["规则内超收数量"] += quantity
        record["本次入库"] += quantity
        record["超收原因"] = f"规则允许超收：{quantity}"
        summary.overreceipt += quantity
        allowance.remaining -= quantity
        summary.remaining -= quantity

    def allocate(self, row: pd.Series, candidates: pd.DataFrame, reason: str) -> None:
        summary = AllocationSummary(remaining=int(row["交货量"]))
        if reason:
            self.add_pending(row, summary, reason)
            return
        self._allocate_normal(candidates, summary)
        allowance = self._allowance(row)
        self._allocate_overreceipt(candidates, summary, allowance)
        if summary.remaining > 0:
            reason = (
                ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED
                if allowance is not None
                else ExceptionReason.RECEIVABLE_EXCEEDED
            )
            self.add_pending(row, summary, reason, over_limit=summary.remaining)

    def result(self, qualified_total: int) -> SelfOperatedInboundResult:
        columns = [
            *self.source_columns,
            *[name for name in ALLOCATION_COLUMNS if name not in self.source_columns],
        ]
        allocation = pd.DataFrame(
            [
                {**record, "_allocation_source_order": source_order}
                for source_order, record in self.records.items()
            ],
            columns=[*columns, "_allocation_source_order"],
        )
        if not allocation.empty:
            allocation = allocation.sort_values(
                ["关联采购单", "_allocation_source_order"], kind="stable"
            ).reset_index(drop=True)
        allocation = allocation[columns]
        pending = pd.DataFrame(self.pending, columns=PENDING_COLUMNS)
        import_total = int(allocation["本次入库"].sum()) if not allocation.empty else 0
        pending_total = int(pending["待处理数量"].sum()) if not pending.empty else 0
        if qualified_total != import_total + pending_total:
            raise RuntimeError("自营仓入库数量守恒校验失败")
        return SelfOperatedInboundResult(
            allocation_rows=allocation,
            pending_rows=pending,
            qualified_total=qualified_total,
            import_total=import_total,
            pending_total=pending_total,
        )
