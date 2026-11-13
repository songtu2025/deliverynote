"""校验采购模板并导出只含本次结果的 Excel 或 ZIP。"""

from copy import copy
from datetime import date
from decimal import Decimal
from io import BytesIO
from itertools import groupby
from pathlib import Path
import re
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from .models import PurchaseConversion, PurchaseRow
from .references import header, open_workbook

TEMPLATE_SHEET = "采购单录入模板"
TEMPLATE_FIELDS = {
    1: "供应商（编码）",
    2: "付款条件（编码）",
    5: "币种（币种符号）",
    7: "自定义采购单号",
    9: "单据备注",
    10: "*目的仓",
    12: "站点",
    14: "*MSKU",
    15: "*物流方式",
    16: "*采购量",
    19: "不含税单价",
    22: "合同交期",
}


def read_template_frame(path: Path) -> pd.DataFrame:
    """仅返回经过检查的第二行表头，绝不返回模板例数据。"""
    with open_workbook(path) as book:
        if TEMPLATE_SHEET not in book.sheetnames:
            raise ValueError(f"采购模板缺少“{TEMPLATE_SHEET}”工作表")
        sheet = book[TEMPLATE_SHEET]
        labels = next(
            sheet.iter_rows(min_row=2, max_row=2, max_col=28, values_only=True),
            (None,) * 28,
        )
        missing = [
            label
            for column, label in TEMPLATE_FIELDS.items()
            if header(labels[column - 1]) != header(label)
        ]
        if missing:
            raise ValueError(f"采购模板第2行缺少或位置错误：{'、'.join(missing)}")
        return pd.DataFrame(
            columns=[str(value) for value in labels if value is not None]
        )


def validate_template(path: Path) -> None:
    """校验表名及十二个目标字段的真实表头位置。"""
    read_template_frame(path)


def _copy_style(original: Any, target: Any) -> None:
    for name in (
        "font",
        "fill",
        "border",
        "alignment",
        "number_format",
        "protection",
        "quotePrefix",
        "pivotButton",
    ):
        setattr(target, name, copy(getattr(original, name)))


def _copy_dimension(original: Any, sheet: Worksheet) -> Any:
    dimension = copy(original)
    dimension.parent = sheet
    # 先重置原工作簿的样式索引，再通过公开属性在目标工作簿注册样式。
    dimension._style = None
    _copy_style(original, dimension)
    return dimension


def _header_book(path: Path) -> Workbook:
    book = Workbook()
    with open_workbook(path, read_only=False) as source:
        original = source[TEMPLATE_SHEET]
        target = book.active
        assert isinstance(target, Worksheet)
        target.title = TEMPLATE_SHEET
        # 在新工作簿中只复制两行表头与样式，避免旧明细、辅助表和定义名称泄露。
        for row in original.iter_rows(min_row=1, max_row=2, max_col=28):
            for cell in row:
                copied = target.cell(cell.row, cell.column, cell.value)
                _copy_style(cell, copied)
        for key, dimension in original.column_dimensions.items():
            target.column_dimensions[key] = _copy_dimension(dimension, target)
        for number in (1, 2):
            target.row_dimensions[number] = _copy_dimension(
                original.row_dimensions[number], target
            )
        for merged in original.merged_cells.ranges:
            if merged.max_row <= 2:
                target.merge_cells(str(merged))
        return book


def _write_workbook(
    template_path: Path, supplier_code: str, rows: tuple[PurchaseRow, ...]
) -> bytes:
    book = _header_book(template_path)
    try:
        sheet = book[TEMPLATE_SHEET]
        for number, row in enumerate(rows, 3):
            values: dict[int, str | int | Decimal | date] = {
                1: supplier_code,
                2: "FKTJ0004",
                5: "CNY",
                7: row.order_number,
                9: row.note,
                10: row.warehouse,
                12: row.site,
                14: row.msku,
                15: "国内快递",
                16: row.quantity,
                19: row.unit_price,
                22: row.delivery_date,
            }
            for column, value in values.items():
                cell = sheet.cell(number, column, value)
                if isinstance(value, str):
                    cell.data_type = "s"
            sheet.cell(number, 22).number_format = "yyyy-mm-dd"
        output = BytesIO()
        book.save(output)
        return output.getvalue()
    finally:
        book.close()


def export_purchase(
    result: PurchaseConversion, template_path: Path, mode: str
) -> bytes:
    """按日期列单号分组，每组均使用同一版本的模板表头。"""
    if mode not in {"merged", "split"}:
        raise ValueError("导出模式必须为 merged 或 split")
    validate_template(template_path)
    if mode == "merged":
        return _write_workbook(template_path, result.supplier_code, result.rows)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for order_number, group in groupby(result.rows, lambda row: row.order_number):
            if re.search(r'[\\/:*?"<>|\x00-\x1f]', order_number):
                raise ValueError("采购单号包含不允许的文件名字符")
            payload = _write_workbook(template_path, result.supplier_code, tuple(group))
            archive.writestr(f"{order_number}.xlsx", payload)
    return output.getvalue()
