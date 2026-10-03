import pandas as pd

from ..exception_reasons import ExceptionReason
from .models import _require_columns


def normalize_delivery_sheet(sheet: pd.DataFrame) -> pd.DataFrame:
    """把交货单明细转换为 SKU、原始站点、交货量。"""
    columns = ["积加SKU", "数量", "站点"]
    _require_columns(sheet, set(columns), "交货单明细表")
    data = sheet[columns].reset_index(drop=True)
    sku = data["积加SKU"].fillna("").astype(str).str.strip()
    footer = sku.isin({"合计", "总计", "Grand Total"})
    if footer.any():
        footer_index = int(footer.to_numpy().argmax())
        if data.iloc[footer_index + 1 :][["数量", "站点"]].notna().any().any():
            raise ValueError("交货单明细表合计行之后仍有交货数据")
        data = data.iloc[:footer_index].copy()
        sku = sku.iloc[:footer_index]

    site = data["站点"].fillna("").astype(str).str.strip()
    present = sku.ne("") | site.ne("") | data["数量"].notna()
    data = data.loc[present]
    if data.empty:
        raise ValueError("交货单明细表没有交货数据")
    sku = sku.loc[present]
    site = site.loc[present].str.removesuffix("站").str.strip()
    quantities = pd.to_numeric(data["数量"], errors="coerce")
    invalid = (
        sku.eq("")
        | site.eq("")
        | quantities.isna()
        | quantities.le(0)
        | quantities.mod(1).ne(0)
    )
    if invalid.any():
        row_number = int(invalid[invalid].index[0]) + 5
        raise ValueError(f"交货单明细表第 {row_number} 行的积加SKU、数量或站点无效")

    result = pd.DataFrame(
        {
            "SKU": sku,
            "原始站点": site,
            "交货量": quantities.astype(int),
        }
    )
    return (
        result.groupby(["SKU", "原始站点"], as_index=False, sort=True)[["交货量"]]
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
        delivery_lines.groupby(["SKU", "原始站点"], as_index=False)[["交货量"]]
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
        if product_matches is not None and len(full_sites) > 1:
            locked_sites = product_matches.loc[
                product_matches["锁仓MKSU"].astype(str).str.strip().eq("锁"),
                "完整站点",
            ].drop_duplicates()
            if not locked_sites.empty:
                full_sites = locked_sites.tolist()

        reason: str
        if not full_sites:
            full_site = ""
            reason = ExceptionReason.PRODUCT_NOT_FOUND
        elif len(full_sites) > 1:
            full_site = "、".join(sorted(full_sites))
            reason = ExceptionReason.AMBIGUOUS_PRODUCT_SITE
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
