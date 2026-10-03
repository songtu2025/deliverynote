"""基础资料工作簿的读取调度与库位文件导出。"""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from ..excel_io import (
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_supplier_workbook,
    validate_self_operated_template_workbook,
    validate_template_workbook,
)
from ..processing.models import POSITION_SOURCE_COLUMNS


def _read_template_workbook(path: Path) -> pd.DataFrame:
    """读取以第二行作为表头的交货模板。"""

    validate_template_workbook(path)
    return pd.read_excel(path, header=1, usecols="A:G")


def _read_self_operated_template_workbook(path: Path) -> pd.DataFrame:
    """读取自营仓入库模板并保持原字段范围。"""

    validate_self_operated_template_workbook(path)
    return pd.read_excel(path, header=0, usecols="A:T")


def _read_frame(kind: str, path: Path) -> pd.DataFrame:
    """按资料类型选择已有读取实现。"""

    readers: dict[str, Callable[[Path], pd.DataFrame]] = {
        "purchase": read_purchase_workbook,
        "product": read_product_workbook,
        "supplier": read_supplier_workbook,
        "position": read_position_workbook,
        "template": _read_template_workbook,
        "inbound_template": _read_self_operated_template_workbook,
    }
    try:
        reader = readers[kind]
    except KeyError as error:
        raise ValueError(f"不支持的输入资料类型：{kind}") from error
    return reader(Path(path))


def write_position_workbook(path: Path, frame: pd.DataFrame) -> None:
    """按库位字段顺序导出 MSKU 视图。"""

    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "MSKU_视图"
    sheet.append(POSITION_SOURCE_COLUMNS)
    for values in frame[POSITION_SOURCE_COLUMNS].itertuples(index=False, name=None):
        sheet.append([None if pd.isna(value) else value for value in values])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
