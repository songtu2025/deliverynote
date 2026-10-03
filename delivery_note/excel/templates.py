"""交货和自营入库模板校验。"""

from copy import copy
from pathlib import Path
from typing import cast

import pandas as pd
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..inbound.models import INBOUND_TEMPLATE_COLUMNS
from ..processing.models import IMPORT_COLUMNS
from .styles import _StyledCell, _excel_value


def _validate_template_headers(
    sheet: Worksheet,
    columns: list[str],
    *,
    row: int,
    message: str,
) -> None:
    """按模板原顺序检查表头，保持各模板的错误提示。"""

    headers = [
        sheet.cell(row=row, column=index).value for index in range(1, len(columns) + 1)
    ]
    if headers != columns:
        raise ValueError(message)


def validate_template_workbook(path: Path) -> None:
    """只读校验官方模板的 A:G 表头和示例格式行。"""
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = cast(Worksheet, workbook.active)
        _validate_template_headers(
            sheet, IMPORT_COLUMNS, row=2, message="官方模板表头与预期字段不一致"
        )
        example_cells = [sheet.cell(row=3, column=column) for column in range(1, 8)]
        if not any(
            cell.value is not None or getattr(cell, "has_style", False)
            for cell in example_cells
        ):
            raise ValueError("官方模板缺少第 3 行示例格式")
    finally:
        workbook.close()


def validate_self_operated_template_workbook(path: Path) -> None:
    """只读校验积加入库模板表头和样式示例行。"""
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = cast(Worksheet, workbook.active)
        _validate_template_headers(
            sheet,
            INBOUND_TEMPLATE_COLUMNS,
            row=1,
            message="积加入库模板表头与预期字段不一致",
        )
        if sheet.max_row < 2:
            raise ValueError("积加入库模板缺少第 2 行示例格式")
    finally:
        workbook.close()


def _populate_import_sheet(
    sheet: Worksheet,
    import_rows: pd.DataFrame,
    *,
    preserve_example_row: bool = False,
) -> None:
    """沿用模板示例样式填充数据，保持两种交货起始行规则。"""

    if list(import_rows.columns) != IMPORT_COLUMNS:
        raise ValueError("正式导入数据字段与官方模板不一致")

    _validate_template_headers(
        sheet, IMPORT_COLUMNS, row=2, message="官方模板表头与预期字段不一致"
    )
    if sheet.max_row < 3:
        raise ValueError("官方模板缺少第 3 行示例格式")

    styles = [
        copy(cast(_StyledCell, sheet.cell(row=3, column=column))._style)
        for column in range(1, 8)
    ]
    row_height = sheet.row_dimensions[3].height
    if sheet.max_row > 3:
        sheet.delete_rows(4, sheet.max_row - 3)
    first_data_row = 4 if preserve_example_row else 3
    if not preserve_example_row:
        for column in range(1, 8):
            sheet.cell(row=3, column=column).value = None

    for row_offset, values in enumerate(import_rows.itertuples(index=False, name=None)):
        row_number = first_data_row + row_offset
        if row_number > 3:
            sheet.row_dimensions[row_number].height = row_height
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_number, column=column)
            cast(_StyledCell, cell)._style = copy(styles[column - 1])
            cell.value = _excel_value(value)
    for row_number in range(first_data_row, first_data_row + len(import_rows)):
        sheet.cell(row=row_number, column=4).number_format = "0"
