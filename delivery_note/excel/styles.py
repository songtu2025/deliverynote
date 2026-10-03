"""Excel 值转换、样式和编辑权限。"""

from copy import copy
from typing import Any, Protocol, cast

import pandas as pd
from openpyxl.styles import Alignment, Protection
from openpyxl.styles.cell_style import StyleArray
from openpyxl.utils.indexed_list import IndexedList
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..processing.models import PENDING_COLUMNS, POSITION_VALUE_COLUMNS


class _StyledCell(Protocol):
    """描述现有样式字段，补足 openpyxl 的类型声明。"""

    _style: StyleArray | None


class _StyleIndex(Protocol):
    """描述工作簿现有的样式索引读取和重建操作。"""

    def __getitem__(self, index: int) -> StyleArray: ...

    def _rebuild_dict(self) -> None: ...


class _WorkbookStyles(Protocol):
    """描述默认单元格保护使用的现有工作簿样式字段。"""

    _protections: IndexedList[Protection]
    _cell_styles: _StyleIndex


def _excel_value(value: Any) -> Any:
    """将空值和 NumPy 标量转为 Excel 可保存的值。"""

    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _set_default_cells_unlocked(workbook: Workbook) -> None:
    """让未显式设置样式的空白单元格默认可编辑。"""
    styles = cast(_WorkbookStyles, workbook)
    unlocked_id = styles._protections.add(Protection(locked=False))
    styles._cell_styles[0].protectionId = unlocked_id
    styles._cell_styles._rebuild_dict()


def _protect_header_only(sheet: Worksheet) -> None:
    """锁定前两行内容，同时允许用户调整导出文件格式。"""
    sheet.protection.sheet = True
    sheet.protection.formatCells = False
    sheet.protection.formatColumns = False
    sheet.protection.formatRows = False
    sheet.protection.selectLockedCells = False
    for row in sheet.iter_rows(
        min_row=1, max_row=2, min_col=1, max_col=sheet.max_column
    ):
        for cell in row:
            styled_cell = cast(_StyledCell, cell)
            styled_cell._style = copy(styled_cell._style)
            cell.protection = Protection(locked=True, hidden=True)
    for row in sheet.iter_rows(
        min_row=3, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column
    ):
        for cell in row:
            styled_cell = cast(_StyledCell, cell)
            styled_cell._style = copy(styled_cell._style)
            protection = cast(Protection, copy(cell.protection))
            protection.locked = False
            cell.protection = protection


def _populate_pending_position_columns(
    sheet: Worksheet, pending_rows: pd.DataFrame
) -> None:
    """保留待处理定位字段、长内容换行和原列宽。"""

    if list(pending_rows.columns) != PENDING_COLUMNS:
        raise ValueError("待处理导入数据字段与预期不一致")
    sheet.column_dimensions["G"].width = 35

    header_style = copy(cast(_StyledCell, sheet.cell(row=2, column=7))._style)
    data_style = copy(cast(_StyledCell, sheet.cell(row=3, column=7))._style)
    row_count = max(len(pending_rows), 1)
    for column, (letter, header) in enumerate(
        zip(("H", "I"), POSITION_VALUE_COLUMNS), start=8
    ):
        header_cell = sheet.cell(row=2, column=column)
        cast(_StyledCell, header_cell)._style = copy(header_style)
        header_cell.value = header
        header_cell.alignment = Alignment(
            horizontal=header_cell.alignment.horizontal,
            vertical=header_cell.alignment.vertical,
            wrap_text=True,
        )
        sheet.column_dimensions[letter].width = 45
        for row_offset in range(row_count):
            cell = sheet.cell(row=3 + row_offset, column=column)
            cast(_StyledCell, cell)._style = copy(data_style)
            if row_offset < len(pending_rows):
                cell.value = _excel_value(pending_rows.iloc[row_offset][header])
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row_offset in range(len(pending_rows)):
        helper_values = pending_rows.iloc[row_offset][POSITION_VALUE_COLUMNS]
        if any(
            isinstance(value, str) and value.startswith("{") for value in helper_values
        ):
            sheet.row_dimensions[3 + row_offset].height = 60
