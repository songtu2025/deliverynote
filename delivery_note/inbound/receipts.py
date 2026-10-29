"""先核对单份文件的累计实收，再交给已有分配器处理本次申请。"""

from typing import Any, Mapping, Sequence

import pandas as pd

from ..processing.delivery_sites import resolve_delivery_sites
from ..processing.keys import _normalize_position_text as key
from .candidates import (
    _apply_site_overrides,
    _resolve_inbound_candidate_sites,
    prepare_inbound_candidates,
)
from .history import OPEN_STATUSES, receipt_quantity, validate_history_frame
from .models import SelfOperatedInboundRequest


def _known_quantity(value):
    try:
        return receipt_quantity(value)
    except ValueError:
        return None


def allocation_frame(inbound: pd.DataFrame) -> pd.DataFrame:
    """历史覆盖全部状态，分配仍只开放既有业务仓型和单据类型。"""
    frame = inbound[inbound["入库状态"].isin(OPEN_STATUSES)].copy()
    if "仓库类型" in frame and "单据类型" in frame:
        frame = frame[
            (frame["仓库类型"].eq("0") & frame["单据类型"].eq("purchase"))
            | (frame["仓库类型"].eq("1") & frame["单据类型"].eq("transfer"))
        ].copy()
    return frame


def _history_for_row(row: dict, matches: pd.DataFrame) -> None:
    if matches.empty:
        # 单号范围已完整校验；无匹配明细的数量由分配器保留为待处理。
        row["history"] = 0
        row["requested"] = row["cumulative"]
        row["notice"] = "未匹配到入库明细，该数量将进入待处理"
        return
    try:
        for _, item in matches.iterrows():
            if str(item.get("历史核对问题") or "") not in {"", "nan"}:
                raise ValueError(str(item["历史核对问题"]))
            if item["入库状态"] not in OPEN_STATUSES | {"COMPLETED"}:
                raise ValueError("存在取消或未知状态的入库单")
            receipt_quantity(item["原始应收货"])
            if "已退货" in matches and receipt_quantity(item["已退货"]):
                raise ValueError("存在退货，需要人工核对")
        history = sum(receipt_quantity(value) for value in matches["已入库"])
        row["history"] = history
        requested = row["cumulative"] - history
        if requested < 0:
            raise ValueError(
                f"累计实收 {row['cumulative']} 小于历史已入库 {history}"
                f"，差额 {abs(requested)}"
            )
        if requested and allocation_frame(matches).empty:
            raise ValueError("仅有已完结单据或非本流程仓库，存在新增数量时需核对")
        row["requested"] = requested
    except ValueError as error:
        row["issue"] = str(error)


def _file_receipt(delivery, products, inbound, choices) -> dict:
    context: dict[str, Any] = {
        "rows": [],
        "delivery_numbers": list(delivery.delivery_numbers),
    }
    try:
        scoped = prepare_inbound_candidates(inbound, delivery.delivery_numbers)
    except ValueError as error:
        scoped = inbound.iloc[:0]
        context["issue"] = str(error)
    resolved = resolve_delivery_sites(delivery.delivery_lines, products)
    if not scoped.empty:
        resolved = _resolve_inbound_candidate_sites(resolved, scoped)
    try:
        resolved = _apply_site_overrides(resolved, choices)
    except ValueError as error:
        context["issue"] = str(error)
    # 多个原始站点指向同一完整站点时，只扣一次该文件的历史。
    grouped: dict[tuple[str, str], dict] = {}
    for _, item in resolved.iterrows():
        group = (item["SKU"], item["完整站点"] or item["原始站点"])
        row = grouped.setdefault(
            group,
            {
                "sku": item["SKU"],
                "original_site": item["原始站点"],
                "full_site": item["完整站点"],
                "cumulative": 0,
                "history": None,
                "requested": None,
                "issue": str(item["异常原因"]),
                "candidates": str(item["完整站点"]).split("、")
                if item["异常原因"]
                else [],
                "order_numbers": [],
                "purchase_numbers": [],
                "item_ids": [],
            },
        )
        row["cumulative"] += int(item["交货量"])
    for row in grouped.values():
        if context.get("issue"):
            row["issue"] = context["issue"]
        if not row["issue"]:
            matches = scoped[
                scoped["_sku_key"].eq(key(row["sku"]))
                & scoped["_site_key"].eq(key(row["full_site"]))
                & scoped["_supplier_key"].eq(key(delivery.supplier_name))
            ]
            row["order_numbers"] = list(dict.fromkeys(matches["入库单号"].tolist()))
            row["purchase_numbers"] = list(
                dict.fromkeys(matches["关联采购单"].tolist())
            )
            row["item_ids"] = matches["积加明细ID"].map(str).tolist()
            row["entries"] = [
                {
                    "item_id": str(item["积加明细ID"]),
                    "order_no": item["入库单号"],
                    "purchase_no": item["关联采购单"],
                    "status": item["入库状态"],
                    "history": _known_quantity(item["已入库"]),
                    "shelf_numbers": str(item.get("分批入库单号") or ""),
                }
                for _, item in matches.iterrows()
            ]
            _history_for_row(row, matches)
        context["rows"].append(row)
    return context


def _mark_overlaps(deliveries, contexts) -> None:
    seen: dict[tuple[str, str, str, str], Any] = {}
    for item in deliveries:
        for row in contexts[item.source_id]["rows"]:
            if row["issue"]:
                continue
            for number in item.delivery_numbers:
                scope = (
                    key(item.supplier_name),
                    key(row["sku"]),
                    key(row["full_site"]),
                    key(number),
                )
                previous = seen.get(scope)
                if previous is not None and previous != item.source_id:
                    row["issue"] = (
                        f"交货单号 {number} 与文件 #{previous} 的累计范围重叠"
                    )
                    for other in contexts[previous]["rows"]:
                        if (
                            key(other["sku"]) == scope[1]
                            and key(other["full_site"]) == scope[2]
                        ):
                            other["issue"] = (
                                f"交货单号 {number} 与文件 #{item.source_id}"
                                " 的累计范围重叠"
                            )
                            other["requested"] = None
                    row["requested"] = None
                seen[scope] = item.source_id


def prepare_receipts(
    deliveries: Sequence[SelfOperatedInboundRequest],
    products: pd.DataFrame,
    inbound: pd.DataFrame,
    file_choices: Mapping[Any, Mapping[tuple[str, str], str]],
) -> tuple[dict[Any, dict], list[SelfOperatedInboundRequest]]:
    """未知数量保留为空；任一核对问题都会阻断整批分配。"""
    inbound = validate_history_frame(inbound)
    contexts = {
        item.source_id: _file_receipt(
            item, products, inbound, file_choices.get(item.source_id, {})
        )
        for item in deliveries
    }
    _mark_overlaps(deliveries, contexts)
    requests = []
    for item in deliveries:
        context = contexts[item.source_id]
        rows = context["rows"]
        context["cumulative_total"] = sum(row["cumulative"] for row in rows)
        context["history_total"] = (
            None
            if any(row["history"] is None for row in rows)
            else sum(row["history"] for row in rows)
        )
        context["requested_total"] = (
            None
            if any(row["issue"] for row in rows)
            else sum(row["requested"] for row in rows)
        )
        context["issue_count"] = sum(bool(row["issue"]) for row in rows)
        if not context["issue_count"]:
            lines = pd.DataFrame(
                [
                    {
                        "SKU": row["sku"],
                        "原始站点": row["original_site"],
                        "交货量": row["requested"],
                    }
                    for row in rows
                ]
            )
            requests.append(
                SelfOperatedInboundRequest(
                    item.source_id, lines, item.delivery_numbers, item.supplier_name
                )
            )
    if any(context["issue_count"] for context in contexts.values()):
        requests = []
    return contexts, requests
