from typing import Iterable, Mapping, MutableMapping, Sequence

import pandas as pd

from .inbound.allocation import InboundAllocator
from .inbound.candidates import (
    _apply_site_overrides,
    _resolve_inbound_candidate_sites,
    prepare_inbound_candidates,
    select_inbound_candidates,
)
from .inbound.models import (
    SelfOperatedInboundBatchResult,
    SelfOperatedInboundItemResult,
    SelfOperatedInboundRequest,
    SelfOperatedInboundResult,
)
from .processing.allocation import AllocationSummary
from .processing.delivery_sites import resolve_delivery_sites
from .processing.models import OverreceiptAllowance, OverreceiptKey


def _joined_original_sites(values: pd.Series) -> str:
    return "、".join(dict.fromkeys(values))


def process_self_operated_inbound(
    delivery_lines: pd.DataFrame,
    delivery_numbers: Sequence[str],
    product_info: pd.DataFrame,
    inbound_rows: pd.DataFrame,
    supplier_name: str,
    *,
    overreceipt_allowances: MutableMapping[OverreceiptKey, OverreceiptAllowance]
    | None = None,
    site_overrides: Mapping[tuple[str, str], str] | None = None,
    overreceipt_limit: int | None = None,
    receivable_balances: MutableMapping[int, int] | None = None,
) -> SelfOperatedInboundResult:
    """按 PO 单号升序分配自营仓实收数量。"""
    if overreceipt_limit is not None and overreceipt_limit < 0:
        raise ValueError("允许超收数量必须为非负整数")
    inbound = prepare_inbound_candidates(inbound_rows, delivery_numbers)
    resolved = resolve_delivery_sites(delivery_lines, product_info)
    resolved = _resolve_inbound_candidate_sites(resolved, inbound)
    resolved = _apply_site_overrides(resolved, site_overrides)
    allocator = InboundAllocator(
        supplier_name=supplier_name,
        source_columns=list(inbound_rows.columns),
        balances=receivable_balances,
        allowances=overreceipt_allowances,
        overreceipt_limit=overreceipt_limit,
    )
    for _, row in resolved[resolved["异常原因"].ne("")].iterrows():
        allocator.add_pending(
            row, AllocationSummary(remaining=int(row["交货量"])), row["异常原因"]
        )
    groups = (
        resolved[resolved["异常原因"].eq("")]
        .groupby(["SKU", "完整站点"], as_index=False, sort=True)
        .agg(
            {
                "原始站点": _joined_original_sites,
                "交货量": "sum",
            }
        )
    )
    for _, row in groups.iterrows():
        candidates, reason = select_inbound_candidates(inbound, row, supplier_name)
        allocator.allocate(row, candidates, reason)
    return allocator.result(int(resolved["交货量"].sum()))


def process_self_operated_inbound_batch(
    deliveries: Iterable[SelfOperatedInboundRequest],
    product_info: pd.DataFrame,
    inbound_rows: pd.DataFrame,
    *,
    overreceipt_limit: int = 0,
    site_overrides: Mapping[tuple[str, str], str] | None = None,
) -> SelfOperatedInboundBatchResult:
    """按用户顺序处理质检单，并共享待入库余额与超收额度。"""

    if overreceipt_limit < 0:
        raise ValueError("允许超收数量必须为非负整数")
    receivable_balances: dict[int, int] = {}
    overreceipt_allowances: dict[OverreceiptKey, OverreceiptAllowance] = {}
    items: list[SelfOperatedInboundItemResult] = []
    for file_order, delivery in enumerate(deliveries, start=1):
        result = process_self_operated_inbound(
            delivery.delivery_lines,
            delivery.delivery_numbers,
            product_info,
            inbound_rows,
            delivery.supplier_name,
            overreceipt_allowances=overreceipt_allowances,
            site_overrides=site_overrides,
            overreceipt_limit=overreceipt_limit,
            receivable_balances=receivable_balances,
        )
        items.append(
            SelfOperatedInboundItemResult(
                source_id=delivery.source_id,
                file_order=file_order,
                delivery_numbers=tuple(delivery.delivery_numbers),
                supplier_name=delivery.supplier_name,
                result=result,
            )
        )

    qualified_total = sum(item.result.qualified_total for item in items)
    import_total = sum(item.result.import_total for item in items)
    pending_total = sum(item.result.pending_total for item in items)
    if qualified_total != import_total + pending_total:
        raise RuntimeError("自营仓入库批次数量守恒校验失败")
    return SelfOperatedInboundBatchResult(
        items=tuple(items),
        qualified_total=qualified_total,
        import_total=import_total,
        pending_total=pending_total,
    )
