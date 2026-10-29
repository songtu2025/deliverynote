"""将完整入库单快照转换为可核对的商品历史，保留关闭单据。"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from ..sync_mapping import normalize_sync_site, sync_text
from .models import INBOUND_TEMPLATE_COLUMNS


HISTORY_COLUMNS = [
    *INBOUND_TEMPLATE_COLUMNS,
    "原始应收货",
    "供应商",
    "入库状态",
    "积加明细ID",
    "历史核对问题",
    "仓库类型",
    "单据类型",
    "分批入库单号",
]
HISTORY_REQUIRED = {"原始应收货", "已入库", "积加明细ID", "入库状态"}
OPEN_STATUSES = {"WAIT_INBOUND", "PART_INBOUND"}


def receipt_quantity(value: Any) -> int:
    """历史数量不能把缺失值或非法值解释为零。"""
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError
        return int(number)
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError("历史数量缺失或不是非负整数") from error


def _shelf_history(order: dict) -> tuple[dict[str, int], dict[str, list[str]]]:
    totals: dict[str, int] = defaultdict(int)
    numbers: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for event in order.get("onShelfOrderList") or []:
        number = sync_text(event.get("orderNo"))
        for item in event.get("onShelfItemList") or []:
            item_id = sync_text(item.get("inboundItemId"))
            key = (number, item_id)
            if not number or not item_id or key in seen:
                raise ValueError("分批入库记录缺少标识或重复")
            seen.add(key)
            if item.get("onShelfType") != "normal":
                raise ValueError("存在次品或未知类型的分批入库")
            totals[item_id] += receipt_quantity(item.get("shelfedNum"))
            numbers[item_id].append(number)
    return totals, numbers


def _item_quantities(order, item, shelf, item_id, issue):
    expected = history = None
    try:
        expected = receipt_quantity(item.get("arriveNum"))
        history = receipt_quantity(item.get("onShelfNum"))
        if history != shelf.get(item_id, 0):
            raise ValueError("已入库与分批入库合计不一致")
        if receipt_quantity(item.get("returnedNum")):
            raise ValueError("存在退货，需要人工核对")
        if (
            receipt_quantity(item.get("exceptionNum"))
            and order.get("orderStatus") in OPEN_STATUSES
        ):
            raise ValueError("开放单据存在已处理差异，需要人工核对")
    except ValueError as failure:
        issue = issue or str(failure)
    return expected, history, issue


def history_frame(orders: list[dict]) -> pd.DataFrame:
    rows = []
    identities: dict[str, dict] = {}
    for order in orders:
        error = ""
        try:
            shelf, numbers = _shelf_history(order)
        except ValueError as failure:
            error, shelf, numbers = str(failure), {}, {}
        for item in order.get("orderItemResultList") or []:
            item_id = sync_text(item.get("id"))
            site, site_error = normalize_sync_site(sync_text(item.get("marketName")))
            issue = error or site_error
            expected, history, issue = _item_quantities(
                order, item, shelf, item_id, issue
            )
            row: dict[str, Any] = {column: "" for column in HISTORY_COLUMNS}
            row.update(
                {
                    "入库单号": sync_text(order.get("orderNo")),
                    "入库仓": sync_text(order.get("warehouseName")),
                    "SKU": sync_text(item.get("sku")),
                    "平台站点": site,
                    "关联交货单/调拨单": sync_text(order.get("releatedCode")),
                    "关联采购单": sync_text(order.get("purchaseCode")),
                    "供应商": sync_text(order.get("supplierName")),
                    "原始应收货": expected,
                    "已入库": history,
                    "应收货": max(expected - history, 0)
                    if expected is not None and history is not None
                    else None,
                    "入库状态": sync_text(order.get("orderStatus")),
                    "积加明细ID": item_id,
                    "历史核对问题": issue,
                    "仓库类型": sync_text(order.get("_receipt_rn_type")),
                    "单据类型": sync_text(order.get("orderType")),
                    "分批入库单号": "、".join(numbers.get(item_id, [])),
                    "产品名称": sync_text(item.get("productName")),
                    "MSKU": sync_text(item.get("msku")),
                    "FNSKU": sync_text(item.get("fnsku")),
                    "关联质检单": sync_text(order.get("qcCode")),
                    "发货单号": sync_text(order.get("shipmentNo")),
                    "已收货": item.get("receiveNum"),
                    "已退货": item.get("returnedNum"),
                    "最大可收货": item.get("maxReceiveNum"),
                }
            )
            if not all(
                row[column]
                for column in (
                    "入库单号",
                    "入库仓",
                    "SKU",
                    "供应商",
                    "关联交货单/调拨单",
                )
            ):
                row["历史核对问题"] = "入库单据标识、仓库、SKU或供应商缺失"
            if not item_id:
                row["历史核对问题"] = "积加明细ID缺失"
            elif item_id in identities:
                if identities[item_id] != row:
                    identities[item_id]["历史核对问题"] = "积加明细ID重复且内容冲突"
                continue
            identities[item_id] = row
            rows.append(row)
    return pd.DataFrame(rows, columns=HISTORY_COLUMNS)


def validate_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """手工来源同样必须提供完整历史字段和唯一明细标识。"""
    missing = HISTORY_REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(
            "历史数据不完整，请重新取数；缺少：" + "、".join(sorted(missing))
        )
    frame = frame.copy()
    if "历史核对问题" not in frame:
        frame["历史核对问题"] = ""
    ids = frame["积加明细ID"].map(sync_text)
    if ids.eq("").any() or ids.duplicated().any():
        raise ValueError("历史数据的积加明细ID为空或重复，请重新取数")
    # 手工文件与接口快照均从原始应收货和历史计算余额，不能混用旧余额。
    for index, row in frame.iterrows():
        try:
            expected = receipt_quantity(row["原始应收货"])
            history = receipt_quantity(row["已入库"])
            frame.at[index, "应收货"] = max(expected - history, 0)
        except ValueError:
            frame.at[index, "历史核对问题"] = "历史数量缺失或不是非负整数"
    return frame
