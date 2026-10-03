from typing import Iterable, Mapping, MutableMapping, Sequence

import pandas as pd

from .exception_reasons import ExceptionReason
from .inbound.candidates import (
    _resolve_inbound_candidate_sites,
    _apply_site_overrides,
    prepare_inbound_candidates,
    select_inbound_candidates,
)
from .processing.models import OverreceiptAllowance, OverreceiptKey
from .processing.keys import make_overreceipt_key
from .processing.delivery_sites import resolve_delivery_sites
from .inbound.models import (
    ALLOCATION_COLUMNS,
    PENDING_COLUMNS,
    SelfOperatedInboundBatchResult,
    SelfOperatedInboundItemResult,
    SelfOperatedInboundRequest,
    SelfOperatedInboundResult,
)


def _pending_row(
    *,
    supplier: str,
    sku: str,
    original_site: str,
    full_site: str,
    quantity: int,
    normal: int,
    overreceipt: int,
    pending: int,
    reason: str,
    over_limit: int = 0,
) -> dict:
    return {
        "供应商": supplier,
        "SKU": sku,
        "原始站点": original_site,
        "完整站点": full_site,
        "质检合格数量": quantity,
        "正常分配数量": normal,
        "规则内超收数量": overreceipt,
        "超过超收规则数量": over_limit,
        "待处理数量": pending,
        "待处理原因": reason,
    }


def _new_allocation_record(
    row: pd.Series,
    source_columns: list[str],
) -> dict:
    record = {column: row[column] for column in source_columns}
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
    return record


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
    source_columns = list(inbound_rows.columns)
    inbound = prepare_inbound_candidates(inbound_rows, delivery_numbers)

    resolved = resolve_delivery_sites(delivery_lines, product_info)
    resolved = _resolve_inbound_candidate_sites(resolved, inbound)
    resolved = _apply_site_overrides(resolved, site_overrides)
    qualified_total = int(resolved["交货量"].sum())
    pending_records: list[dict] = []
    for _, row in resolved[resolved["异常原因"].ne("")].iterrows():
        quantity = int(row["交货量"])
        pending_records.append(
            _pending_row(
                supplier=supplier_name,
                sku=row["SKU"],
                original_site=row["原始站点"],
                full_site=row["完整站点"],
                quantity=quantity,
                normal=0,
                overreceipt=0,
                pending=quantity,
                reason=row["异常原因"],
            )
        )

    resolved_groups = (
        resolved[resolved["异常原因"].eq("")]
        .groupby(["SKU", "完整站点"], as_index=False, sort=True)
        .agg(
            {
                "原始站点": lambda values: "、".join(dict.fromkeys(values)),
                "交货量": "sum",
            }
        )
    )
    allocation_records: dict[int, dict] = {}
    generated_allowances: dict[OverreceiptKey, OverreceiptAllowance] = {}

    for _, delivery in resolved_groups.iterrows():
        sku = delivery["SKU"]
        full_site = delivery["完整站点"]
        quantity = int(delivery["交货量"])
        candidates, reason = select_inbound_candidates(inbound, delivery, supplier_name)
        if reason:
            pending_records.append(
                _pending_row(
                    supplier=supplier_name,
                    sku=sku,
                    original_site=delivery["原始站点"],
                    full_site=full_site,
                    quantity=quantity,
                    normal=0,
                    overreceipt=0,
                    pending=quantity,
                    reason=reason,
                )
            )
            continue

        remaining = quantity
        normal_total = 0
        for index, candidate in candidates.iterrows():
            available = int(candidate["_receivable"])
            if receivable_balances is not None:
                available = receivable_balances.setdefault(int(index), available)
            normal = min(remaining, available)
            if normal <= 0:
                continue
            record = allocation_records.setdefault(
                index,
                _new_allocation_record(candidate, source_columns),
            )
            record["正常分配数量"] += normal
            record["本次入库"] += normal
            normal_total += normal
            remaining -= normal
            if receivable_balances is not None:
                receivable_balances[int(index)] = available - normal
            if remaining == 0:
                break

        allowance = None
        allowance_key = make_overreceipt_key(supplier_name, sku, full_site)
        if overreceipt_allowances is not None:
            allowance = overreceipt_allowances.get(allowance_key)
            if allowance is None and overreceipt_limit is not None:
                allowance = overreceipt_allowances.setdefault(
                    allowance_key,
                    OverreceiptAllowance(
                        remaining=overreceipt_limit,
                        destination_warehouse="",
                    ),
                )
        elif overreceipt_limit is not None:
            allowance = generated_allowances.setdefault(
                allowance_key,
                OverreceiptAllowance(
                    remaining=overreceipt_limit,
                    destination_warehouse="",
                ),
            )
        overreceipt = 0
        if remaining > 0 and allowance is not None and allowance.remaining > 0:
            overreceipt = min(remaining, allowance.remaining)
            last_index = candidates.index[-1]
            last_candidate = candidates.iloc[-1]
            record = allocation_records.setdefault(
                last_index,
                _new_allocation_record(last_candidate, source_columns),
            )
            record["规则内超收数量"] += overreceipt
            record["本次入库"] += overreceipt
            record["超收原因"] = f"规则允许超收：{overreceipt}"
            allowance.remaining -= overreceipt
            remaining -= overreceipt

        if remaining > 0:
            reason = (
                ExceptionReason.OVERRECEIPT_LIMIT_EXCEEDED
                if allowance is not None
                else ExceptionReason.RECEIVABLE_EXCEEDED
            )
            pending_records.append(
                _pending_row(
                    supplier=supplier_name,
                    sku=sku,
                    original_site=delivery["原始站点"],
                    full_site=full_site,
                    quantity=quantity,
                    normal=normal_total,
                    overreceipt=overreceipt,
                    pending=remaining,
                    reason=reason,
                    over_limit=remaining,
                )
            )

    output_columns = [
        *source_columns,
        *[column for column in ALLOCATION_COLUMNS if column not in source_columns],
    ]
    allocation_frame = pd.DataFrame(
        [
            {**record, "_allocation_source_order": source_order}
            for source_order, record in allocation_records.items()
        ],
        columns=[*output_columns, "_allocation_source_order"],
    )
    if not allocation_frame.empty:
        allocation_frame = allocation_frame.sort_values(
            ["关联采购单", "_allocation_source_order"],
            kind="stable",
        ).reset_index(drop=True)
    allocation_frame = allocation_frame[output_columns]
    pending_frame = pd.DataFrame(pending_records, columns=PENDING_COLUMNS)
    import_total = (
        int(allocation_frame["本次入库"].sum()) if not allocation_frame.empty else 0
    )
    pending_total = (
        int(pending_frame["待处理数量"].sum()) if not pending_frame.empty else 0
    )
    if qualified_total != import_total + pending_total:
        raise RuntimeError("自营仓入库数量守恒校验失败")

    return SelfOperatedInboundResult(
        allocation_rows=allocation_frame,
        pending_rows=pending_frame,
        qualified_total=qualified_total,
        import_total=import_total,
        pending_total=pending_total,
    )


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
