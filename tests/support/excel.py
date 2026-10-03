"""Excel 模板测试复用的最小工作簿。"""

from openpyxl import Workbook

from delivery_note.inbound.models import INBOUND_TEMPLATE_COLUMNS
from delivery_note.processing.models import IMPORT_COLUMNS


def make_import_template() -> Workbook:
    """构造保留提示、合并区域、表头和示例行的交货模板。"""

    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet["A1"] = "模板提示"
    sheet.merge_cells("A1:G1")
    sheet.append(IMPORT_COLUMNS)
    sheet.append(["示例仓", "示例供应商", "示例SKU", 1, "示例站点", "", ""])
    return workbook


def make_inbound_template() -> Workbook:
    """构造带原表头和第二行示例的积加入库模板。"""

    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = "批量入库"
    sheet.append(INBOUND_TEMPLATE_COLUMNS)
    sheet.append(["示例"] * len(INBOUND_TEMPLATE_COLUMNS))
    return workbook


def make_template_preview_workbook(
    kind: str, active_index: int = 1, *, auxiliary_valid: bool = True
) -> Workbook:
    """构造活动模板和内容不同的辅助表，覆盖表顺序、公式和空值。"""

    inbound = kind == "inbound_template"
    workbook = make_inbound_template() if inbound else make_import_template()
    columns = INBOUND_TEMPLATE_COLUMNS if inbound else IMPORT_COLUMNS
    header_row = 1 if inbound else 2
    example_row = header_row + 1
    sheet = workbook.worksheets[0]
    sheet.title = "活动模板"
    sheet.cell(row=example_row, column=1).value = "活动示例"
    sheet.cell(row=example_row, column=len(columns)).value = None
    sheet.cell(row=example_row, column=len(columns) - 1).value = "=1+1"
    sheet.cell(row=header_row, column=len(columns) + 1).value = "额外字段"
    sheet.cell(row=example_row, column=len(columns) + 1).value = "不应读取"
    values = [
        sheet.cell(row=example_row, column=index).value
        for index in range(1, len(columns) + 1)
    ]
    values[0] = "活动数据"
    sheet.append(values)
    auxiliary = workbook.copy_worksheet(sheet)
    auxiliary.title = "辅助模板"
    auxiliary.cell(row=example_row, column=1).value = "辅助示例"
    auxiliary.cell(row=example_row + 1, column=1).value = "辅助数据"
    if not auxiliary_valid:
        auxiliary.cell(row=header_row, column=1).value = "错误表头"
    if active_index == 1:
        workbook.move_sheet(auxiliary, offset=-1)
    workbook.active = active_index
    workbook.create_sheet("隐藏说明").sheet_state = "hidden"
    return workbook
