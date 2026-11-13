"""读取采购日期列及明细，校验数量、单价和批次编号。"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel

from .references import header, text


@dataclass(frozen=True)
class SourceBatch:
    sequence: int
    column: int
    source_site: str
    delivery_date: date
    note: str


def order_prefix(sheet: Any) -> str:
    value = text(sheet["A2"].value)
    match = re.search(r"采购批次编号\s*[:：]\s*[^-]+-(.+)", value)
    if not match or not match.group(1).strip():
        raise ValueError("采购单A2缺少有效的采购批次编号，例如 QX-JQ2026040304")
    prefix = match.group(1).strip()
    if re.search(r'[\\/:*?"<>|\x00-\x1f]', prefix) or prefix in {".", ".."}:
        raise ValueError("采购单A2采购批次编号包含不允许的文件名字符")
    return prefix


def parse_date(value: object, epoch: datetime, location: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            converted = from_excel(value, epoch)
            if isinstance(converted, datetime):
                return converted.date()
        except (ValueError, OverflowError):
            pass
    normalized = (
        re.sub(r"[年/.]", "-", text(value)).replace("月", "-").replace("日", "")
    )
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"采购单{location}交货日期无效，请填写完整年月日")


def price_column(sheet: Any) -> int:
    matches = [cell.column for cell in sheet[6] if "单价" in header(cell.value)]
    if len(matches) != 1:
        raise ValueError("采购单第6行必须有唯一的单价表头（如单价（含包装））")
    if header(sheet["B6"].value).upper() != "SKU":
        raise ValueError("采购单B6必须为SKU表头")
    return int(matches[0])


def cached_value(raw_cell: Any, sheet: Any, label: str) -> Any:
    value = sheet[raw_cell.coordinate].value
    if raw_cell.data_type == "f" and value is None:
        raise ValueError(
            f"采购单{raw_cell.coordinate}{label}公式没有缓存结果，请用Excel重新计算并保存"
        )
    return value


def _date_columns(
    sheet: Any,
    raw_sheet: Any,
    sites: dict[int, tuple[int, str]],
    epoch: datetime,
    detail_numbers: list[int],
) -> list[int]:
    columns = []
    for column in range(1, raw_sheet.max_column + 1):
        raw_cell = raw_sheet.cell(8, column)
        _, site = sites.get(column, (0, ""))
        if raw_cell.value in (None, ""):
            if site and any(
                raw_sheet.cell(row, column).value not in (None, "", 0)
                for row in detail_numbers
            ):
                raise ValueError(f"采购单{raw_cell.coordinate}缺少交货日期")
            continue
        if header(raw_cell.value) in {"合计", "总计", "小计"}:
            continue
        if site:
            cached_value(raw_cell, sheet, "交货日期")
            columns.append(column)
            continue
        try:
            parse_date(sheet.cell(8, column).value, epoch, raw_cell.coordinate)
        except ValueError:
            continue
        raise ValueError(f"采购单{get_column_letter(column)}7缺少站点")
    return columns


def source_batches(sheet: Any, epoch: datetime, raw_sheet: Any) -> list[SourceBatch]:
    sites: dict[int, tuple[int, str]] = {}
    for cell in sheet[7]:
        if text(cell.value):
            sites[cell.column] = (cell.column, text(cell.value))
    for merged in sheet.merged_cells.ranges:
        if merged.min_row == merged.max_row == 7:
            site = text(sheet.cell(7, merged.min_col).value)
            for column in range(merged.min_col, merged.max_col + 1):
                sites[column] = (merged.min_col, site)
    date_columns = _date_columns(
        sheet, raw_sheet, sites, epoch, [number for number, _ in detail_rows(sheet)]
    )
    if not date_columns:
        raise ValueError("采购单第7-8行缺少站点和交货日期列")
    groups = list(dict.fromkeys(sites[column][0] for column in date_columns))
    notes = [text(cell.value) for cell in sheet[6] if text(cell.value)]
    if len(notes) < len(groups) + 2:
        raise ValueError("采购单第6行的站点备注数量不足")
    group_notes = dict(zip(groups, notes[-len(groups) :]))
    return [
        SourceBatch(
            sequence,
            column,
            sites[column][1],
            parse_date(
                sheet.cell(8, column).value, epoch, f"{get_column_letter(column)}8"
            ),
            group_notes[sites[column][0]],
        )
        for sequence, column in enumerate(date_columns, 1)
    ]


def decimal_value(value: object, location: str, label: str) -> Decimal:
    try:
        number = Decimal(text(value))
    except InvalidOperation:
        raise ValueError(f"采购单{location}{label}必须为有效数字") from None
    if not number.is_finite() or number < 0 or isinstance(value, bool):
        raise ValueError(f"采购单{location}{label}必须为非负数字")
    return number


def quantity_value(value: object, location: str) -> int:
    # 空数量单元格与零相同；所有已填写的非法数值都明确报错。
    if value is None or text(value) == "":
        return 0
    number = decimal_value(value, location, "数量")
    rounded = number.to_integral_value()
    if abs(number - rounded) > Decimal("1e-8"):
        raise ValueError(f"采购单{location}数量必须为整数，不能截断小数")
    return int(rounded)


def detail_rows(sheet: Any) -> Iterator[tuple[int, str]]:
    """明细必须在合计处结束，避免将底部业务条款作为 SKU。"""
    for number, cells in enumerate(sheet.iter_rows(min_row=9), 9):
        sku = text(cells[1].value)
        if any(
            re.fullmatch(r"[总合小]计[:：]?", header(cell.value)) for cell in cells[:2]
        ):
            return
        if not sku:
            if any(text(cell.value) for cell in cells[2:]):
                raise ValueError(f"采购单B{number}缺少SKU，不能丢弃该行数据")
            continue
        yield number, sku
    raise ValueError("采购单A/B列缺少合计结束行，无法确认明细范围")
