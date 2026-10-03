"""供应商交货、自营入库及基础资料工作簿读取。"""

from pathlib import Path

import pandas as pd

from ..inbound.models import INBOUND_COLUMNS, SelfOperatedDeliverySource
from ..inbound.normalization import normalize_self_operated_delivery_sheet
from ..processing.delivery_sites import normalize_delivery_sheet
from ..processing.models import POSITION_SOURCE_COLUMNS

PURCHASE_COLUMNS = ["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"]


PRODUCT_COLUMNS = ["SKU", "店铺/站点", "品类A", "锁仓MKSU"]


SUPPLIER_REQUIRED_COLUMNS = ["供应商编号", "供应商名称", "状态"]


SUPPLIER_COLUMNS = [*SUPPLIER_REQUIRED_COLUMNS, "供应商别名"]


def read_delivery_workbook(path: Path) -> pd.DataFrame:
    """读取明细工作表并复用交货数量整理。"""

    with pd.ExcelFile(path) as workbook:
        if "明细" not in workbook.sheet_names:
            raise ValueError("交货单缺少“明细”工作表")
        sheet = pd.read_excel(workbook, sheet_name="明细", header=3)
    return normalize_delivery_sheet(sheet)


def read_self_operated_delivery_workbook(
    path: Path,
) -> SelfOperatedDeliverySource:
    """读取质检明细并保留自营仓来源信息。"""

    sheet = pd.read_excel(path, sheet_name="明细", header=3)
    return normalize_self_operated_delivery_sheet(sheet)


def read_self_operated_inbound_workbook(path: Path) -> pd.DataFrame:
    """读取待入库数据并检查原必要字段。"""

    rows = pd.read_excel(path)
    missing = sorted(INBOUND_COLUMNS - set(rows.columns))
    if missing:
        raise ValueError(f"自营仓收货入库单缺少必要字段：{', '.join(missing)}")
    return rows


def read_product_workbook(path: Path) -> pd.DataFrame:
    """按原字段选择读取商品资料。"""

    return pd.read_excel(path, usecols=PRODUCT_COLUMNS)


def read_purchase_workbook(path: Path) -> pd.DataFrame:
    """按原字段选择读取采购资料。"""

    return pd.read_excel(path, usecols=PURCHASE_COLUMNS)


def read_supplier_workbook(path: Path) -> pd.DataFrame:
    """读取供应商资料并补充缺省别名列。"""

    rows = pd.read_excel(path)
    missing = [column for column in SUPPLIER_REQUIRED_COLUMNS if column not in rows]
    if missing:
        raise ValueError(f"供应商资料缺少必要字段：{', '.join(missing)}")
    if "供应商别名" not in rows:
        rows["供应商别名"] = ""
    return rows[SUPPLIER_COLUMNS]


def read_position_workbook(path: Path) -> pd.DataFrame:
    """读取 MSKU 视图的有效定位字段。"""

    return pd.read_excel(path, sheet_name="MSKU_视图", usecols=POSITION_SOURCE_COLUMNS)
