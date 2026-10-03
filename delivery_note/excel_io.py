"""Excel 读取、模板校验和导出的统一入口。"""

from copy import copy
from pathlib import Path
from typing import Any, cast

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Protection
from openpyxl.worksheet.worksheet import Worksheet

from .excel.readers import (
    PRODUCT_COLUMNS,
    PURCHASE_COLUMNS,
    read_delivery_workbook,
    read_position_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_self_operated_delivery_workbook,
    read_self_operated_inbound_workbook,
    read_supplier_workbook,
)
from .excel.styles import _StyledCell
from .excel.templates import (
    _validate_template_headers,
    validate_self_operated_template_workbook,
    validate_template_workbook,
)
from .inbound.models import INBOUND_TEMPLATE_COLUMNS
from .processing.models import (
    IMPORT_COLUMNS,
    PENDING_COLUMNS,
    POSITION_VALUE_COLUMNS,
    BatchResult,
)

__all__ = [
    "PRODUCT_COLUMNS",
    "PURCHASE_COLUMNS",
    "read_delivery_workbook",
    "read_self_operated_delivery_workbook",
    "read_self_operated_inbound_workbook",
    "read_product_workbook",
    "read_purchase_workbook",
    "read_supplier_workbook",
    "read_position_workbook",
    "validate_template_workbook",
    "validate_self_operated_template_workbook",
    "write_import_workbook",
    "write_delivery_workbook",
    "write_self_operated_inbound_workbook",
]


def _excel_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


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


def write_import_workbook(
    template_path: Path,
    output_path: Path,
    import_rows: pd.DataFrame,
) -> None:
    """复制官方模板，在第 3 行起写入可导入数据。"""
    workbook = load_workbook(template_path)
    _populate_import_sheet(cast(Worksheet, workbook.active), import_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def write_self_operated_inbound_workbook(
    template_path: Path,
    output_path: Path,
    allocation_rows: pd.DataFrame,
) -> None:
    """复制积加入库模板，从第 2 行写入本次可入库数据。"""
    missing = [
        column
        for column in INBOUND_TEMPLATE_COLUMNS
        if column not in allocation_rows.columns
    ]
    if missing:
        raise ValueError(f"积加入库数据缺少字段：{', '.join(missing)}")

    workbook = load_workbook(template_path)
    sheet = cast(Worksheet, workbook.active)
    _validate_template_headers(
        sheet,
        INBOUND_TEMPLATE_COLUMNS,
        row=1,
        message="积加入库模板表头与预期字段不一致",
    )
    if sheet.max_row < 2:
        raise ValueError("积加入库模板缺少第 2 行示例格式")

    styles = [
        copy(cast(_StyledCell, sheet.cell(row=2, column=column))._style)
        for column in range(1, len(INBOUND_TEMPLATE_COLUMNS) + 1)
    ]
    row_height = sheet.row_dimensions[2].height
    sheet.delete_rows(2, sheet.max_row - 1)
    export_rows = allocation_rows[INBOUND_TEMPLATE_COLUMNS]
    for row_offset, values in enumerate(
        export_rows.itertuples(index=False, name=None),
        start=2,
    ):
        sheet.row_dimensions[row_offset].height = row_height
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_offset, column=column)
            cast(_StyledCell, cell)._style = copy(styles[column - 1])
            cell.value = _excel_value(value)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def _set_default_cells_unlocked(workbook) -> None:
    """让未显式设置样式的空白单元格默认可编辑。"""
    unlocked_id = workbook._protections.add(Protection(locked=False))
    workbook._cell_styles[0].protectionId = unlocked_id
    workbook._cell_styles._rebuild_dict()


def _protect_header_only(sheet) -> None:
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
            cell._style = copy(cell._style)
            cell.protection = Protection(locked=True, hidden=True)
    for row in sheet.iter_rows(
        min_row=3, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column
    ):
        for cell in row:
            cell._style = copy(cell._style)
            protection = copy(cell.protection)
            protection.locked = False
            cell.protection = protection


def _populate_pending_position_columns(sheet, pending_rows: pd.DataFrame) -> None:
    if list(pending_rows.columns) != PENDING_COLUMNS:
        raise ValueError("待处理导入数据字段与预期不一致")
    sheet.column_dimensions["G"].width = 35

    header_style = copy(sheet.cell(row=2, column=7)._style)
    data_style = copy(sheet.cell(row=3, column=7)._style)
    row_count = max(len(pending_rows), 1)
    for column, (letter, header) in enumerate(
        zip(("H", "I"), POSITION_VALUE_COLUMNS), start=8
    ):
        header_cell = sheet.cell(row=2, column=column)
        header_cell._style = copy(header_style)
        header_cell.value = header
        header_cell.alignment = copy(header_cell.alignment)
        header_cell.alignment = Alignment(
            horizontal=header_cell.alignment.horizontal,
            vertical=header_cell.alignment.vertical,
            wrap_text=True,
        )
        sheet.column_dimensions[letter].width = 45
        for row_offset in range(row_count):
            cell = sheet.cell(row=3 + row_offset, column=column)
            cell._style = copy(data_style)
            if row_offset < len(pending_rows):
                cell.value = _excel_value(pending_rows.iloc[row_offset][header])
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row_offset in range(len(pending_rows)):
        helper_values = pending_rows.iloc[row_offset][POSITION_VALUE_COLUMNS]
        if any(
            isinstance(value, str) and value.startswith("{") for value in helper_values
        ):
            sheet.row_dimensions[3 + row_offset].height = 60


def write_delivery_workbook(
    template_path: Path,
    output_path: Path,
    result: BatchResult,
    import_rows: pd.DataFrame,
    pending_rows: pd.DataFrame,
) -> None:
    """输出交货导入和可编辑的待处理数据，保持表头保护。"""
    workbook = load_workbook(template_path)
    import_sheet = cast(Worksheet, workbook.active)
    import_sheet.title = "交货导入"
    pending_sheet = workbook.copy_worksheet(import_sheet)
    pending_sheet.title = "待处理导入"
    pending_sheet.protection = copy(import_sheet.protection)

    _set_default_cells_unlocked(workbook)
    _populate_import_sheet(
        import_sheet,
        import_rows,
        preserve_example_row=True,
    )
    _populate_import_sheet(pending_sheet, pending_rows[IMPORT_COLUMNS])
    _populate_pending_position_columns(pending_sheet, pending_rows)
    _protect_header_only(import_sheet)
    _protect_header_only(pending_sheet)
    workbook.active = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
