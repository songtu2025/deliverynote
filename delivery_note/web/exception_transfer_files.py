from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
    products = read_product_workbook(Path(version.storage_path))
    return sorted(
        {
            "AMAZON:" + str(site).strip()
            for site in products.loc[products["SKU"].eq(sku), "店铺/站点"].dropna()
            if str(site).strip()
        }
    )


@dataclass
class TransferFile:
    supplier_code: str
    rows: dict[tuple[str, str], int] = field(default_factory=dict)
    sites: dict[str, str] = field(default_factory=dict)

    def add(self, sku: str, full_site: str, quantity: int) -> None:
        short_site = full_site.rsplit(":", 1)[-1]
        key = f"{sku}	{short_site}"
        if key in self.sites and self.sites[key] != full_site:
            raise HTTPException(
                status_code=400,
                detail=f"{sku} / {short_site} 对应多个完整站点，请分批转交该供应商",
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
        supplier_name = str(enabled.iloc[0]["供应商名称"]).strip()
        date_label = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%y%m%d")
        name = _safe_filename(f"{date_label}-{supplier_name}-转交货0箱.xlsx")
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
