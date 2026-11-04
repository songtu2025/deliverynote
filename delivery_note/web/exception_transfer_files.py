from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy.orm import Session

from ..config import resolve_supplier
from ..excel_io import read_delivery_workbook, read_product_workbook
from .models import Batch, InputVersion
from .uploads import _safe_filename


def transfer_sites(session: Session, batch: Batch, sku: str) -> list[str]:
    version = session.get(InputVersion, batch.product_version_id)
    if version is None:
        raise HTTPException(status_code=409, detail="批次锁定的商品资料不存在")
    return list(_product_sites(version.id, version.storage_path).get(sku, ()))


@lru_cache(maxsize=8)
def _product_sites(version_id: int, storage_path: str) -> dict[str, tuple[str, ...]]:
    """缓存锁定版本的站点映射；路径用于隔离不同数据库的同号版本。"""
    products = read_product_workbook(Path(storage_path))
    sites: dict[str, set[str]] = {}
    for sku, site in (
        products[["SKU", "店铺/站点"]].dropna().itertuples(index=False, name=None)
    ):
        if str(site).strip():
            sites.setdefault(str(sku), set()).add("AMAZON:" + str(site).strip())
    return {sku: tuple(sorted(values)) for sku, values in sites.items()}


@dataclass
class TransferFile:
    supplier_code: str
    original_name: str
    rows: dict[tuple[str, str], int] = field(default_factory=dict)
    sites: dict[str, str] = field(default_factory=dict)

    def add(self, sku: str, full_site: str, quantity: int) -> None:
        short_site = full_site.rsplit(":", 1)[-1]
        key = f"{sku}	{short_site}"
        if key in self.sites and self.sites[key] != full_site:
            raise HTTPException(
                status_code=400,
                detail=f"{sku} / {short_site} 对应多个完整站点，请分批转交该文件",
            )
        self.sites[key] = full_site
        row_key = (sku, short_site)
        self.rows[row_key] = self.rows.get(row_key, 0) + quantity

    def write(self, directory: Path, suppliers: pd.DataFrame) -> tuple[str, Path]:
        enabled = suppliers[
            suppliers["供应商编号"].astype(str).str.strip().eq(self.supplier_code)
            & suppliers["状态"].astype(str).str.strip().eq("启用")
        ]
        if enabled.empty:
            raise HTTPException(
                status_code=400,
                detail=f"启用供应商资料中找不到编码 {self.supplier_code}",
            )
        name = _safe_filename(self.original_name)
        supplier = resolve_supplier(Path(name), suppliers)
        if supplier.code != self.supplier_code:
            raise HTTPException(
                status_code=400,
                detail=f"生成文件名识别的供应商与来源编码 {self.supplier_code} 不一致",
            )
        path = directory / name
        workbook = Workbook()
        sheet = workbook.active
        if sheet is None:
            raise RuntimeError("无法创建交货工作表")
        sheet.title = "明细"
        sheet.append([])
        sheet.append([])
        sheet.append([])
        sheet.append(["积加SKU", "数量", "站点"])
        for (sku, site), quantity in self.rows.items():
            sheet.append([sku, quantity, site])
        workbook.save(path)
        workbook.close()
        parsed = read_delivery_workbook(path)
        expected = {
            (sku, site): quantity for (sku, site), quantity in self.rows.items()
        }
        actual = {
            (row["SKU"], row["原始站点"]): int(row["交货量"])
            for _, row in parsed.iterrows()
        }
        if actual != expected:
            raise HTTPException(
                status_code=400, detail="生成交货文件自检失败，SKU 或站点被读取规则改变"
            )
        return name, path
