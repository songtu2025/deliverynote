from dataclasses import dataclass
import re
from typing import Mapping, MutableMapping, Sequence

import pandas as pd

from .pipeline import (
    OverreceiptAllowance,
    OverreceiptKey,
    make_overreceipt_key,
    resolve_delivery_sites,
)


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


def _require_columns(frame: pd.DataFrame, required: set[str], source: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{source}缺少必要字段：{', '.join(missing)}")


def _text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _normalized_text(value) -> str:
    return _text(value).upper()


def normalize_self_operated_delivery_sheet(
    sheet: pd.DataFrame,
) -> SelfOperatedDeliverySource:
    """读取明细表，独立提取交货单号并汇总质检合格数量。"""
    _require_columns(sheet, SOURCE_COLUMNS, "自营仓交货单明细")

    data = sheet.copy()
    data["积加SKU"] = data["积加SKU"].map(_text)
    data["站点"] = data["站点"].map(_text)
    data = data[data["积加SKU"].ne("") & data["站点"].ne("")].copy()
    data = data[
        ~data["积加SKU"].str.fullmatch(r"合计|总计|Grand Total", case=False)
    ].copy()
    if data.empty:
        raise ValueError("自营仓交货单明细没有有效商品数据")

    raw_quantities = data["实收数量"]
    quantities = pd.to_numeric(raw_quantities, errors="coerce")
    blank_quantities = raw_quantities.map(_text).eq("")
    if (blank_quantities | quantities.isna()).any():
        raise ValueError("自营仓交货单实收数量存在空值或无效值")
    if ((quantities < 0) | (quantities % 1 != 0)).any():
        raise ValueError("自营仓交货单实收数量必须为非负整数")

    valid_numbers: set[str] = set()
    invalid_values: list[str] = []
    for value in data["交货单号"]:
        delivery_number = _text(value)
        if not delivery_number:
            continue
        if re.fullmatch(r"LN\d+", delivery_number, flags=re.IGNORECASE):
            valid_numbers.add(delivery_number.upper())
        elif delivery_number not in invalid_values:
            invalid_values.append(delivery_number)
    if not valid_numbers:
        raise ValueError("自营仓交货单未提取到有效交货单号")

    data["交货量"] = quantities.astype(int)
    data["SKU"] = data["积加SKU"]
    data["原始站点"] = data["站点"].str.removesuffix("站")
    delivery_lines = (
        data.groupby(["SKU", "原始站点"], as_index=False, sort=True)["交货量"]
        .sum()
        .sort_values(["SKU", "原始站点"], kind="stable")
        .reset_index(drop=True)
    )
    return SelfOperatedDeliverySource(
        delivery_lines=delivery_lines,
        delivery_numbers=tuple(sorted(valid_numbers)),
        invalid_delivery_values=tuple(invalid_values),
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


def _resolve_inbound_candidate_sites(
    resolved: pd.DataFrame,
    inbound: pd.DataFrame,
) -> pd.DataFrame:
    """使用已筛选自营仓候选消除产品信息中的站点歧义。"""
    site_candidates: dict[tuple[str, str], set[str]] = {}
    for _, row in inbound[["_sku_key", "_site_key"]].drop_duplicates().iterrows():
        site = row["_site_key"]
        country = site.rsplit(":", 1)[-1]
        site_candidates.setdefault((row["_sku_key"], country), set()).add(site)

    result = resolved.copy()
    ambiguous = result["异常原因"].eq("产品信息站点不唯一")
    for index, row in result[ambiguous].iterrows():
        candidates = site_candidates.get(
            (
                _normalized_text(row["SKU"]),
                _normalized_text(row["原始站点"]),
            ),
            set(),
        )
        product_sites = [
            site.strip() for site in str(row["完整站点"]).split("、") if site.strip()
        ]
        matches = [
            site for site in product_sites if _normalized_text(site) in candidates
        ]
        if len(matches) == 1:
            result.at[index, "完整站点"] = matches[0]
            result.at[index, "异常原因"] = ""
        elif matches:
            result.at[index, "完整站点"] = "、".join(matches)
        else:
            result.at[index, "完整站点"] = ""
            result.at[index, "异常原因"] = "未找到自营仓入库单"
    return result


def _apply_site_overrides(
    resolved: pd.DataFrame,
    site_overrides: Mapping[tuple[str, str], str] | None,
) -> pd.DataFrame:
    """应用操作员对仍有歧义的完整站点选择。"""
    if not site_overrides:
        return resolved

    normalized_overrides = {
        (_normalized_text(sku), _normalized_text(site)): _text(full_site)
        for (sku, site), full_site in site_overrides.items()
    }
    result = resolved.copy()
    ambiguous = result["异常原因"].eq("产品信息站点不唯一")
    for index, row in result[ambiguous].iterrows():
        selected = normalized_overrides.get(
            (
                _normalized_text(row["SKU"]),
                _normalized_text(row["原始站点"]),
            )
        )
        if not selected:
            continue
        candidates = {
            _normalized_text(site)
            for site in str(row["完整站点"]).split("、")
            if site.strip()
        }
        if _normalized_text(selected) not in candidates:
            raise ValueError(
                f"人工选择站点不在候选范围：{row['SKU']} / {row['原始站点']}"
            )
        result.at[index, "完整站点"] = selected
        result.at[index, "异常原因"] = ""
    return result


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
) -> SelfOperatedInboundResult:
    """按 PO 单号升序分配自营仓实收数量。"""
    if overreceipt_limit is not None and overreceipt_limit < 0:
        raise ValueError("允许超收数量必须为非负整数")
    if overreceipt_limit is not None and overreceipt_allowances is not None:
        raise ValueError("不能同时传入超收额度和统一允许超收数量")
    _require_columns(inbound_rows, INBOUND_COLUMNS, "自营仓收货入库单")
    normalized_numbers = tuple(
        sorted({_normalized_text(value) for value in delivery_numbers if _text(value)})
    )
    if not normalized_numbers:
        raise ValueError("没有可用于筛选的交货单号")

    source_columns = list(inbound_rows.columns)
    inbound = inbound_rows.copy().reset_index(drop=True)
    inbound["_source_order"] = inbound.index
    inbound["_sku_key"] = inbound["SKU"].map(_normalized_text)
    inbound["_site_key"] = inbound["平台站点"].map(_normalized_text)
    inbound["_delivery_key"] = inbound["关联交货单/调拨单"].map(_normalized_text)
    inbound["_po_key"] = inbound["关联采购单"].map(_normalized_text)
    inbound["_supplier_key"] = inbound["供应商"].map(_normalized_text)
    inbound["_receivable"] = pd.to_numeric(inbound["应收货"], errors="coerce")

    available_numbers = set(inbound["_delivery_key"])
    missing_numbers = sorted(set(normalized_numbers) - available_numbers)
    if missing_numbers:
        raise ValueError(f"自营仓导出缺少交货单号：{', '.join(missing_numbers)}")
    inbound = inbound[inbound["_delivery_key"].isin(normalized_numbers)].copy()

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
    supplier_key = _normalized_text(supplier_name)
    generated_allowances: dict[OverreceiptKey, OverreceiptAllowance] = {}

    for _, delivery in resolved_groups.iterrows():
        sku = delivery["SKU"]
        full_site = delivery["完整站点"]
        quantity = int(delivery["交货量"])
        candidates = inbound[
            inbound["_sku_key"].eq(_normalized_text(sku))
            & inbound["_site_key"].eq(_normalized_text(full_site))
        ].copy()
        if candidates.empty:
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
                    reason="未找到自营仓入库单",
                )
            )
            continue

        candidates = candidates[candidates["_supplier_key"].eq(supplier_key)].copy()
        if candidates.empty:
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
                    reason="供应商不一致",
                )
            )
            continue

        candidates = candidates[candidates["_po_key"].ne("")].copy()
        if candidates.empty:
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
                    reason="PO名称为空",
                )
            )
            continue

        valid_receivable = (
            candidates["_receivable"].notna()
            & candidates["_receivable"].ge(0)
            & candidates["_receivable"].mod(1).eq(0)
        )
        candidates = candidates[valid_receivable].copy()
        if candidates.empty:
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
                    reason="应收货无效",
                )
            )
            continue

        candidates = candidates.sort_values(
            ["_po_key", "_source_order"],
            kind="stable",
        )
        remaining = quantity
        normal_total = 0
        for index, candidate in candidates.iterrows():
            normal = min(remaining, int(candidate["_receivable"]))
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
            if remaining == 0:
                break

        allowance = None
        allowance_key = make_overreceipt_key(supplier_name, sku, full_site)
        if overreceipt_allowances is not None:
            allowance = overreceipt_allowances.get(allowance_key)
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
            reason = "超出允许超收量" if allowance is not None else "超出应收货"
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
