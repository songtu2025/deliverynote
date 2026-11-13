"""采购源表按日期列转换为积加采购导入明细。"""

from pathlib import Path

import pandas as pd

from ..config import supplier_aliases
from ..excel.readers import read_supplier_workbook
from .models import PurchaseConversion, PurchaseRow
from .references import (
    open_workbook,
    normalize_country,
    read_purchase_products,
    read_warehouse_frame,
    text,
    unique_value,
)
from .source import (
    cached_value,
    decimal_value,
    detail_rows,
    order_prefix,
    price_column,
    quantity_value,
    source_batches,
)


def _supplier_code(filename: str, path: Path) -> str:
    name = Path(filename.replace("\\", "/")).stem.split("-", 1)[0].strip()
    frame = read_supplier_workbook(path)
    codes = set()
    for _, row in frame.iterrows():
        identifiers = [text(row["供应商名称"]), *supplier_aliases(row["供应商别名"])]
        if text(row["状态"]) == "启用" and name in identifiers:
            code = text(row["供应商编号"])
            if not code or code == "nan":
                raise ValueError("供应商资料缺少供应商编号")
            codes.add(code)
    if len(codes) != 1:
        raise ValueError("文件名首个“-”前的供应商名称或别名未匹配唯一的启用供应商")
    return codes.pop()


def _destination(
    sku: str, source_site: str, products: pd.DataFrame, warehouses: pd.DataFrame
) -> tuple[str, str, str]:
    site_name = source_site.removesuffix("站")
    if site_name.upper() == "TK":
        return "TK本地仓", "共享", sku
    country = normalize_country(site_name)
    site, msku = unique_value(products, sku, country)
    (warehouse,) = unique_value(warehouses, sku)
    if not site.startswith("AMAZON:"):
        site = f"AMAZON:{site}"
    return warehouse, site, msku


def convert_purchase(
    path: Path,
    filename: str,
    supplier_path: Path,
    product_path: Path,
    warehouse_path: Path,
) -> PurchaseConversion:
    """转换一份采购工作簿；任意明细无效时整体失败。"""
    supplier_code = _supplier_code(filename, supplier_path)
    products = read_purchase_products(product_path)
    warehouses = read_warehouse_frame(warehouse_path)
    with (
        open_workbook(path, read_only=False) as book,
        open_workbook(path, read_only=False, data_only=False) as raw_book,
    ):
        if "采购单" not in book.sheetnames:
            raise ValueError("采购单缺少“采购单”工作表")
        sheet = book["采购单"]
        raw_sheet = raw_book["采购单"]
        prefix = order_prefix(sheet)
        price_col = price_column(sheet)
        batches = source_batches(sheet, book.epoch, raw_sheet)
        details = list(detail_rows(sheet))
        rows = []
        skipped_zero_count = 0
        for batch in batches:
            for number, sku in details:
                cell = sheet.cell(number, batch.column)
                quantity = quantity_value(
                    cached_value(raw_sheet[cell.coordinate], sheet, "数量"),
                    cell.coordinate,
                )
                if quantity == 0:
                    skipped_zero_count += 1
                    continue
                price_cell = sheet.cell(number, price_col)
                price = decimal_value(price_cell.value, price_cell.coordinate, "单价")
                try:
                    warehouse, site, msku = _destination(
                        sku, batch.source_site, products, warehouses
                    )
                except ValueError as error:
                    raise ValueError(f"采购单{cell.coordinate}：{error}") from None
                rows.append(
                    PurchaseRow(
                        f"{prefix}{batch.sequence:02d}",
                        batch.source_site,
                        sku,
                        site,
                        msku,
                        warehouse,
                        quantity,
                        price,
                        batch.delivery_date,
                        batch.note,
                    )
                )
        if not rows:
            raise ValueError("采购单没有大于零的可导出数量")
        return PurchaseConversion(
            supplier_code, prefix, tuple(rows), skipped_zero_count
        )
