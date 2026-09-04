"""由命令行、接口和后台任务共用的应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .config import (
    SupplierIdentity,
    build_ordered_document_note,
)
from .pipeline import (
    IMPORT_COLUMNS,
    BatchResult,
    OverreceiptPolicy,
    build_manual_import_rows,
    build_overreceipt_allowances,
    build_purchase_balance_ledger,
    process_data,
)


@dataclass(frozen=True)
class DeliveryRequest:
    """批次中按明确顺序排列的单个交货来源。"""

    source_id: str
    delivery_rows: pd.DataFrame
    supplier_name: str
    supplier_code: str
    source_name: str = ""


@dataclass(frozen=True)
class DeliveryItemResult:
    source_id: str
    file_order: int
    document_note: str
    result: BatchResult


@dataclass(frozen=True)
class DeliveryBatchResult:
    items: tuple[DeliveryItemResult, ...]
    delivery_total: int
    import_total: int
    manual_total: int


@dataclass(frozen=True)
class SplitPart:
    quantity: int
    destination: str = ""
    site: str = ""
    supplier_code: str = ""
    sku: str = ""
    delivery_note: str = ""
    resolved: bool = True


@dataclass(frozen=True)
class SplitProjection:
    import_rows: pd.DataFrame
    pending_rows: pd.DataFrame
    import_total: int
    pending_total: int


def validate_split(
    expected_quantity: int, parts: Iterable[SplitPart]
) -> tuple[SplitPart, ...]:
    """校验无损拆分，不修改原始异常记录。"""

    validated = tuple(parts)
    if not validated:
        raise ValueError("拆分明细不能为空")
    if any(
        isinstance(part.quantity, bool) or int(part.quantity) != part.quantity
        for part in validated
    ):
        raise ValueError("拆分数量必须是整数")
    if any(part.quantity <= 0 for part in validated):
        raise ValueError("拆分数量必须大于 0")
    if sum(part.quantity for part in validated) != expected_quantity:
        raise ValueError(f"拆分数量合计必须等于 {expected_quantity}")
    return validated


def project_split(
    exception: pd.Series,
    parts: Iterable[SplitPart],
    supplier_code: str,
    document_note: str,
) -> SplitProjection:
    """把一次守恒拆分投影为正式导入行和仍待处理行。"""

    expected_quantity = int(exception["人工处理量"])
    validated = validate_split(expected_quantity, parts)
    base_row = (
        build_manual_import_rows(pd.DataFrame([exception]), supplier_code)
        .iloc[0]
        .to_dict()
    )
    base_row["单据备注"] = document_note

    import_rows: list[dict] = []
    pending_rows: list[dict] = []
    for part in validated:
        row = dict(base_row)
        row["*本次交货量"] = part.quantity
        if part.destination:
            row["*目的仓"] = part.destination
        if part.site:
            row["*站点"] = part.site
        if part.supplier_code:
            row["*供应商编码"] = part.supplier_code
        if part.sku:
            row["*SKU"] = part.sku
        if part.delivery_note:
            row["交货备注"] = part.delivery_note

        if part.resolved:
            required = ("*目的仓", "*供应商编码", "*SKU", "*站点")
            missing = [column for column in required if not str(row[column]).strip()]
            if missing or "、" in str(row["*站点"]):
                raise ValueError("已解决拆分缺少必要字段或站点仍不唯一")
            import_rows.append(row)
        else:
            pending_rows.append(row)

    import_frame = pd.DataFrame(import_rows, columns=IMPORT_COLUMNS)
    pending_frame = pd.DataFrame(pending_rows, columns=IMPORT_COLUMNS)
    import_total = (
        int(import_frame["*本次交货量"].sum()) if not import_frame.empty else 0
    )
    pending_total = (
        int(pending_frame["*本次交货量"].sum()) if not pending_frame.empty else 0
    )
    if import_total + pending_total != expected_quantity:
        raise RuntimeError("拆分投影数量不守恒")
    return SplitProjection(
        import_rows=import_frame,
        pending_rows=pending_frame,
        import_total=import_total,
        pending_total=pending_total,
    )


def process_delivery_batch(
    deliveries: Iterable[DeliveryRequest],
    product_info: pd.DataFrame,
    purchase_data: pd.DataFrame,
    position_data: pd.DataFrame | None = None,
    overreceipt_policy: OverreceiptPolicy | None = None,
) -> DeliveryBatchResult:
    """让同批次文件共享一份内存采购余额快照。"""

    purchase_ledger = build_purchase_balance_ledger(purchase_data)
    overreceipt_allowances = None
    if overreceipt_policy is not None:
        if position_data is None:
            raise ValueError("启用超收规则时必须提供排查表")
        overreceipt_allowances = build_overreceipt_allowances(
            purchase_data,
            position_data,
            overreceipt_policy,
        )
    items: list[DeliveryItemResult] = []
    for file_order, delivery in enumerate(deliveries, start=1):
        document_note = ""
        if delivery.source_name:
            document_note = build_ordered_document_note(
                Path(delivery.source_name),
                SupplierIdentity(
                    name=delivery.supplier_name,
                    code=delivery.supplier_code,
                ),
                file_order,
            )

        result = process_data(
            delivery.delivery_rows,
            product_info,
            purchase_data,
            delivery.supplier_name,
            delivery.supplier_code,
            overreceipt_allowances=overreceipt_allowances,
            _purchase_ledger=purchase_ledger,
        )
        if document_note:
            import_rows = result.import_rows.copy()
            import_rows["单据备注"] = document_note
            result = BatchResult(
                import_rows=import_rows,
                exception_rows=result.exception_rows,
                delivery_total=result.delivery_total,
                import_total=result.import_total,
                manual_total=result.manual_total,
            )
        items.append(
            DeliveryItemResult(
                source_id=delivery.source_id,
                file_order=file_order,
                document_note=document_note,
                result=result,
            )
        )

    delivery_total = sum(item.result.delivery_total for item in items)
    import_total = sum(item.result.import_total for item in items)
    manual_total = sum(item.result.manual_total for item in items)
    if delivery_total != import_total + manual_total:
        raise RuntimeError("批次交货总量不守恒")
    return DeliveryBatchResult(
        items=tuple(items),
        delivery_total=delivery_total,
        import_total=import_total,
        manual_total=manual_total,
    )
