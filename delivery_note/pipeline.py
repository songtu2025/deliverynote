import json
from dataclasses import dataclass
from typing import MutableMapping

import pandas as pd

from .config import PURCHASE_STATUSES, warehouse_sort_key


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
    "已下单可售天数",
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


def normalize_delivery_sheet(sheet: pd.DataFrame) -> pd.DataFrame:
    """把当前供应商汇总表转换为 SKU、原始站点、交货量明细。"""
    sku_columns = [
        column
        for column in sheet.columns
        if str(column).strip().upper().endswith("SKU")
    ]
    if len(sku_columns) != 1:
        raise ValueError("交货单汇总表未找到唯一的 SKU 字段")
    sheet = sheet.rename(columns={sku_columns[0]: "SKU"})
    site_columns = [column for column in sheet.columns if str(column).endswith("站")]
    if not site_columns:
        raise ValueError("交货单汇总表未找到以“站”结尾的站点列")

    data = sheet[["SKU", *site_columns]].copy()
    data = data.dropna(subset=["SKU"])
    sku_text = data["SKU"].astype(str).str.strip()
    data = data[~sku_text.str.fullmatch(r"总计|Grand Total", case=False)]

    result = data.melt(
        id_vars=["SKU"],
        value_vars=site_columns,
        var_name="原始站点",
        value_name="交货量",
    )
    raw_quantities = result["交货量"]
    quantities = pd.to_numeric(raw_quantities, errors="coerce")
    invalid = raw_quantities.notna() & quantities.isna()
    if invalid.any():
        raise ValueError("交货单存在无法识别的数量")

    result["交货量"] = quantities.fillna(0)
    positive = result["交货量"] > 0
    non_integer = positive & (result["交货量"] % 1 != 0)
    if non_integer.any():
        raise ValueError("交货量必须为整数")

    result = result[positive].copy()
    result["SKU"] = result["SKU"].astype(str).str.strip()
    result["原始站点"] = result["原始站点"].astype(str).str.removesuffix("站")
    result["交货量"] = result["交货量"].astype(int)
    return (
        result.groupby(["SKU", "原始站点"], as_index=False, sort=True)["交货量"]
        .sum()
        .sort_values(["SKU", "原始站点"], kind="stable")
        .reset_index(drop=True)
    )


def resolve_delivery_sites(
    delivery_lines: pd.DataFrame,
    product_info: pd.DataFrame,
) -> pd.DataFrame:
    """复用商品信息和锁仓标识，为交货数量解析唯一完整站点。"""
    _require_columns(delivery_lines, {"SKU", "原始站点", "交货量"}, "交货明细")
    _require_columns(
        product_info, {"SKU", "店铺/站点", "品类A", "锁仓MKSU"}, "产品信息"
    )

    delivery = (
        delivery_lines.groupby(["SKU", "原始站点"], as_index=False)["交货量"]
        .sum()
        .sort_values(["SKU", "原始站点"], kind="stable")
        .reset_index(drop=True)
    )
    delivery["交货量"] = delivery["交货量"].astype(int)

    relevant_skus = set(delivery["SKU"])
    products = product_info[
        product_info["SKU"].isin(relevant_skus)
        & product_info["SKU"].notna()
        & product_info["店铺/站点"].notna()
        & product_info["品类A"].notna()
    ].copy()
    products["原始站点"] = (
        products["店铺/站点"].astype(str).str.rsplit(":", n=1).str[-1]
    )
    products["完整站点"] = "AMAZON:" + products["店铺/站点"].astype(str)
    products = products[["SKU", "原始站点", "完整站点", "锁仓MKSU"]].drop_duplicates()
    product_groups = {
        key: group for key, group in products.groupby(["SKU", "原始站点"], sort=False)
    }

    resolved_rows: list[dict] = []
    for _, delivery_row in delivery.iterrows():
        product_matches = product_groups.get(
            (delivery_row["SKU"], delivery_row["原始站点"])
        )
        full_sites = (
            product_matches["完整站点"].drop_duplicates().tolist()
            if product_matches is not None
            else []
        )
        if len(full_sites) > 1:
            locked_sites = product_matches.loc[
                product_matches["锁仓MKSU"].astype(str).str.strip().eq("锁"),
                "完整站点",
            ].drop_duplicates()
            if not locked_sites.empty:
                full_sites = locked_sites.tolist()

        if not full_sites:
            full_site = ""
            reason = "产品信息未匹配"
        elif len(full_sites) > 1:
            full_site = "、".join(sorted(full_sites))
            reason = "产品信息站点不唯一"
        else:
            full_site = full_sites[0]
            reason = ""
        resolved_rows.append(
            {
                "SKU": delivery_row["SKU"],
                "原始站点": delivery_row["原始站点"],
                "交货量": int(delivery_row["交货量"]),
                "完整站点": full_site,
                "异常原因": reason,
            }
        )

    return pd.DataFrame(
        resolved_rows,
        columns=["SKU", "原始站点", "交货量", "完整站点", "异常原因"],
    )


def _append_exception(
    exceptions: list[dict],
    delivery_row: pd.Series,
    full_site: str | None,
    destination_warehouse: str | None,
    allocated: int,
    manual: int,
    reason: str,
    *,
    purchase_allocated: int = 0,
    overreceipt_allocated: int = 0,
    overreceipt_remaining: int | None = None,
) -> None:
    exceptions.append(
        {
            "SKU": delivery_row["SKU"],
            "原始站点": delivery_row["原始站点"],
            "完整站点": full_site or "",
            "目的仓": destination_warehouse or "",
            "交货量": int(delivery_row["交货量"]),
            "已自动分配量": allocated,
            "人工处理量": manual,
            "异常原因": reason,
            "正常采购分配量": purchase_allocated,
            "超收规则分配量": overreceipt_allocated,
            "超收剩余额度": overreceipt_remaining,
        }
    )


def build_manual_import_rows(
    exception_rows: pd.DataFrame,
    supplier_code: str,
) -> pd.DataFrame:
    """把异常数量转换为可补录后再次导入的官方模板字段。"""
    _require_columns(exception_rows, set(EXCEPTION_COLUMNS), "异常明细")
    rows: list[dict] = []

    for _, exception in exception_rows.iterrows():
        reason = str(exception["异常原因"])
        full_site = "" if pd.isna(exception["完整站点"]) else str(exception["完整站点"])
        original_site = (
            "" if pd.isna(exception["原始站点"]) else str(exception["原始站点"])
        )
        destination_warehouse = (
            "" if pd.isna(exception["目的仓"]) else exception["目的仓"]
        )
        manual_quantity = int(exception["人工处理量"])
        site = "" if reason == "产品信息站点不唯一" else full_site
        note = reason
        if reason in {"超出采购未交量", "超出允许超收量"}:
            note = f"{reason}：{manual_quantity}"
        elif reason == "产品信息未匹配" and original_site:
            note = f"{reason}；原始站点：{original_site}"
        elif reason == "产品信息站点不唯一" and full_site:
            note = f"{reason}：{full_site}"

        rows.append(
            {
                "*目的仓": destination_warehouse,
                "*供应商编码": supplier_code,
                "*SKU": exception["SKU"],
                "*本次交货量": manual_quantity,
                "*站点": site,
                "单据备注": "",
                "交货备注": note,
            }
        )

    return pd.DataFrame(rows, columns=IMPORT_COLUMNS)


def _normalize_position_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _normalize_pending_site(value) -> str:
    site = _normalize_position_text(value)
    if site.count(":") >= 2:
        return site.split(":", 1)[1]
    return site


def make_overreceipt_key(supplier, sku, site) -> OverreceiptKey:
    return (
        _normalize_position_text(supplier),
        _normalize_position_text(sku),
        _normalize_position_text(site),
    )


def build_overreceipt_allowances(
    purchase_rows: pd.DataFrame,
    position_rows: pd.DataFrame,
    policy: OverreceiptPolicy,
) -> dict[OverreceiptKey, OverreceiptAllowance]:
    """按供应商、商品编码和站点生成唯一的绝对超收额度。"""

    _require_columns(
        purchase_rows,
        {"单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"},
        "采购需求",
    )
    _require_columns(position_rows, set(POSITION_SOURCE_COLUMNS), "排查表")

    purchases = purchase_rows[purchase_rows["单据状态"].isin(PURCHASE_STATUSES)].copy()
    purchases["未交量"] = pd.to_numeric(purchases["未交量"], errors="coerce").fillna(0)
    purchases = purchases[purchases["未交量"] > 0]
    if purchases.empty or not policy.allowed_warehouses:
        return {}

    positions = position_rows[POSITION_SOURCE_COLUMNS].copy()
    positions["_site_key"] = positions["店铺-站点"].map(_normalize_position_text)
    positions["_sku_key"] = positions["积加SKU"].map(_normalize_position_text)
    position_groups = {
        key: group
        for key, group in positions.groupby(["_site_key", "_sku_key"], sort=False)
    }

    purchases["_supplier_key"] = purchases["供应商"].map(_normalize_position_text)
    purchases["_sku_key"] = purchases["SKU"].map(_normalize_position_text)
    purchases["_site_key"] = purchases["平台站点"].map(_normalize_position_text)
    allowances: dict[OverreceiptKey, OverreceiptAllowance] = {}
    group_columns = ["_supplier_key", "_sku_key", "_site_key"]
    for key, purchase_group in purchases.groupby(group_columns, sort=False):
        position_key = (_normalize_pending_site(key[2]), key[1])
        position_group = position_groups.get(position_key)
        if position_group is None or position_group.empty:
            continue

        scales = [
            "" if pd.isna(value) else str(value).strip()
            for value in position_group["规模定位"]
        ]
        if any(not scale for scale in scales) or len(set(scales)) != 1:
            continue
        limit = policy.limit_for(scales[0])
        if limit <= 0:
            continue

        eligible_warehouses = sorted(
            {
                str(value).strip()
                for value in purchase_group["目的仓"]
                if not pd.isna(value)
                and str(value).strip() in policy.allowed_warehouses
            },
            key=warehouse_sort_key,
        )
        if not eligible_warehouses:
            continue
        allowances[key] = OverreceiptAllowance(
            remaining=limit,
            destination_warehouse=eligible_warehouses[0],
        )
    return allowances


def _position_value(value):
    if pd.isna(value):
        return ""
    if isinstance(value, str):
        return value.strip()
    value = value.item() if hasattr(value, "item") else value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def enrich_pending_import_rows(
    pending_rows: pd.DataFrame,
    position_rows: pd.DataFrame,
) -> pd.DataFrame:
    """按店铺站点和积加 SKU 为待处理数据补充定位信息。"""
    _require_columns(pending_rows, set(IMPORT_COLUMNS), "待处理导入")
    _require_columns(position_rows, set(POSITION_SOURCE_COLUMNS), "排查表")

    result = pending_rows[IMPORT_COLUMNS].copy()
    for column in POSITION_VALUE_COLUMNS:
        result[column] = pd.Series("", index=result.index, dtype=object)
    if result.empty:
        return result[PENDING_COLUMNS]

    positions = position_rows[POSITION_SOURCE_COLUMNS].copy()
    positions["_site_key"] = positions["店铺-站点"].map(_normalize_position_text)
    positions["_sku_key"] = positions["积加SKU"].map(_normalize_position_text)
    positions = positions[positions["_site_key"].ne("") & positions["_sku_key"].ne("")]
    pending_keys = {
        (
            _normalize_pending_site(site),
            _normalize_position_text(sku),
        )
        for site, sku in zip(result["*站点"], result["*SKU"])
    }
    positions = positions[
        [
            (site_key, sku_key) in pending_keys
            for site_key, sku_key in zip(
                positions["_site_key"],
                positions["_sku_key"],
            )
        ]
    ]
    groups = {
        key: group.copy()
        for key, group in positions.groupby(["_site_key", "_sku_key"], sort=False)
    }
    scale_order = {"短尾": 0, "中尾": 1, "长尾": 2}

    for index, pending in result.iterrows():
        key = (
            _normalize_pending_site(pending["*站点"]),
            _normalize_position_text(pending["*SKU"]),
        )
        matches = groups.get(key)
        if matches is None or matches.empty:
            continue
        if len(matches) == 1:
            for column in POSITION_VALUE_COLUMNS:
                result.at[index, column] = _position_value(matches.iloc[0][column])
            continue

        matches["_msku"] = matches["MSKU"].map(_normalize_position_text)
        if matches["_msku"].eq("").any() or matches["_msku"].duplicated().any():
            raise ValueError("排查表重复键内的 MSKU 必须非空且唯一")
        matches["_scale_order"] = matches["规模定位"].map(
            lambda value: scale_order.get(str(value).strip(), 3)
        )
        matches = matches.sort_values(["_scale_order", "_msku"], kind="stable")
        for column in POSITION_VALUE_COLUMNS:
            mapping = {
                str(row["MSKU"]).strip(): _position_value(row[column])
                for _, row in matches.iterrows()
            }
            result.at[index, column] = json.dumps(
                mapping, ensure_ascii=False, separators=(",", ":")
            )

    return result[PENDING_COLUMNS]


def process_data(
    delivery_lines: pd.DataFrame,
    product_info: pd.DataFrame,
    purchase_rows: pd.DataFrame,
    supplier_name: str,
    supplier_code: str | None = None,
    overreceipt_allowances: MutableMapping[OverreceiptKey, OverreceiptAllowance]
    | None = None,
) -> BatchResult:
    """完成产品映射、采购需求汇总和交货数量分配。"""
    supplier_code = supplier_code or supplier_name
    _require_columns(delivery_lines, {"SKU", "原始站点", "交货量"}, "交货明细")
    _require_columns(
        product_info, {"SKU", "店铺/站点", "品类A", "锁仓MKSU"}, "产品信息"
    )
    _require_columns(
        purchase_rows,
        {"单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"},
        "采购需求",
    )

    delivery = resolve_delivery_sites(delivery_lines, product_info)

    purchases = purchase_rows[
        purchase_rows["单据状态"].isin(PURCHASE_STATUSES)
        & purchase_rows["供应商"].eq(supplier_name)
    ].copy()
    purchases["未交量"] = pd.to_numeric(purchases["未交量"], errors="coerce").fillna(0)
    purchases = purchases[purchases["未交量"] > 0]
    needs = (
        purchases.groupby(["SKU", "供应商", "平台站点", "目的仓"], as_index=False)[
            "未交量"
        ]
        .sum()
        .reset_index(drop=True)
    )
    need_indexes = {}
    for key, group in needs.groupby(["SKU", "平台站点"], sort=False):
        indexes = group.index.tolist()
        indexes.sort(
            key=lambda index: warehouse_sort_key(str(needs.at[index, "目的仓"]))
        )
        need_indexes[key] = indexes

    import_rows: list[dict] = []
    exceptions: list[dict] = []

    for _, delivery_row in delivery.iterrows():
        delivery_quantity = int(delivery_row["交货量"])
        if delivery_row["异常原因"]:
            _append_exception(
                exceptions,
                delivery_row,
                delivery_row["完整站点"],
                None,
                0,
                delivery_quantity,
                delivery_row["异常原因"],
            )
            continue

        full_site = delivery_row["完整站点"]
        candidate_indexes = need_indexes.get(
            (delivery_row["SKU"], full_site),
            [],
        )

        remaining = delivery_quantity
        allocated = 0
        purchase_allocated = 0
        overreceipt_allocated = 0
        last_destination_warehouse = ""
        for index in candidate_indexes:
            available = int(needs.at[index, "未交量"])
            quantity = min(remaining, available)
            if quantity <= 0:
                continue
            destination_warehouse = needs.at[index, "目的仓"]
            import_rows.append(
                {
                    "*目的仓": destination_warehouse,
                    "*供应商编码": supplier_code,
                    "*SKU": delivery_row["SKU"],
                    "*本次交货量": quantity,
                    "*站点": full_site,
                    "单据备注": "",
                    "交货备注": "",
                }
            )
            needs.at[index, "未交量"] = available - quantity
            remaining -= quantity
            allocated += quantity
            purchase_allocated += quantity
            last_destination_warehouse = destination_warehouse
            if remaining == 0:
                break

        allowance_key = make_overreceipt_key(
            supplier_name,
            delivery_row["SKU"],
            full_site,
        )
        allowance = (
            overreceipt_allowances.get(allowance_key)
            if overreceipt_allowances is not None
            else None
        )
        if remaining > 0 and allowance is not None and allowance.remaining > 0:
            quantity = min(remaining, allowance.remaining)
            import_rows.append(
                {
                    "*目的仓": allowance.destination_warehouse,
                    "*供应商编码": supplier_code,
                    "*SKU": delivery_row["SKU"],
                    "*本次交货量": quantity,
                    "*站点": full_site,
                    "单据备注": "",
                    "交货备注": f"{OVERRECEIPT_NOTE_PREFIX}：{quantity}",
                }
            )
            allowance.remaining -= quantity
            remaining -= quantity
            allocated += quantity
            overreceipt_allocated += quantity
            last_destination_warehouse = allowance.destination_warehouse

        if remaining > 0:
            if allowance is not None:
                reason = "超出允许超收量"
            else:
                reason = (
                    "超出采购未交量" if candidate_indexes else "未找到可交货采购需求"
                )
            if allocated > 0 and allowance is None:
                import_rows[-1]["交货备注"] = f"{reason}：{remaining}"
            _append_exception(
                exceptions,
                delivery_row,
                full_site,
                last_destination_warehouse,
                allocated,
                remaining,
                reason,
                purchase_allocated=purchase_allocated,
                overreceipt_allocated=overreceipt_allocated,
                overreceipt_remaining=(
                    allowance.remaining if allowance is not None else None
                ),
            )

    import_frame = pd.DataFrame(import_rows, columns=IMPORT_COLUMNS)
    exception_frame = pd.DataFrame(exceptions, columns=RESULT_EXCEPTION_COLUMNS)
    delivery_total = int(delivery["交货量"].sum())
    import_total = (
        int(import_frame["*本次交货量"].sum()) if not import_frame.empty else 0
    )
    manual_total = (
        int(exception_frame["人工处理量"].sum()) if not exception_frame.empty else 0
    )
    if delivery_total != import_total + manual_total:
        raise RuntimeError("数量守恒校验失败")

    return BatchResult(
        import_rows=import_frame,
        exception_rows=exception_frame,
        delivery_total=delivery_total,
        import_total=import_total,
        manual_total=manual_total,
    )
