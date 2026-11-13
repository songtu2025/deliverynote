"""从商品信息读取采购字段，并读取SKU仓库资料。"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import pandas as pd
from openpyxl import load_workbook

from ..excel.readers import read_product_workbook

PURCHASE_PRODUCT_COLUMNS = ["国家", "SKU", "店铺/站点", "MSKU"]
WAREHOUSE_COLUMNS = ["SKU", "仓库"]
DEFAULT_COUNTRIES = {
    "美国": "US",
    "英国": "UK",
    "德国": "DE",
    "日本": "JP",
    "加拿大": "CA",
}
EMPTY_ROW_LIMIT = 32


@contextmanager
def open_workbook(
    path: Path, read_only: bool = True, *, data_only: bool = True
) -> Iterator[Any]:
    """显式管理源文件句柄，解析未完成或 ZIP 损坏时也允许即时删除上传。"""
    with path.open("rb") as source:
        try:
            book = load_workbook(source, read_only=read_only, data_only=data_only)
        except (BadZipFile, KeyError, ParseError, OSError, ValueError):
            raise ValueError("Excel文件格式损坏或不是有效的.xlsx工作簿") from None
        try:
            yield book
        finally:
            book.close()


def text(value: object) -> str:
    """统一 Excel 空白及文本两端空格。"""
    return "" if value is None else str(value).strip()


def header(value: object) -> str:
    """忽略必要字段标记及表头内空格。"""
    return re.sub(r"[\s*＊]", "", text(value))


def _bounded_rows(sheet: Any, first: int, last: int) -> Iterator[tuple[int, list[str]]]:
    """连续空行后停止，避免格式化到 Excel 末行的附件被全表扫描。"""
    empty_count = 0
    for number, values in enumerate(
        sheet.iter_rows(min_col=first, max_col=last, values_only=True), 1
    ):
        cells = [text(value) for value in values]
        if not any(cells):
            empty_count += 1
            if empty_count >= EMPTY_ROW_LIMIT:
                break
            continue
        empty_count = 0
        yield number, cells


def _read_table(path: Path, columns: list[str], first: int, last: int) -> pd.DataFrame:
    with open_workbook(path) as book:
        candidates = [(book.worksheets[0], 1, len(columns))]
        if "辅助计算" in book.sheetnames:
            candidates.append((book["辅助计算"], first, last))
        for sheet, start, end in candidates:
            rows = iter(_bounded_rows(sheet, start, end))
            first_row = next(rows, None)
            if first_row is None:
                continue
            labels = [header(value) for value in first_row[1]]
            if not set(columns).issubset(labels):
                continue
            indices = [labels.index(column) for column in columns]
            records = []
            for _, values in rows:
                record = [values[index] for index in indices]
                if not any(record):
                    continue
                # 历史资料允许无关行不完整；命中本次SKU时才校验必填输出。
                records.append(record)
            if not records:
                raise ValueError(f"{sheet.title}没有有效的{'、'.join(columns)}资料")
            return (
                pd.DataFrame(records, columns=columns)
                .drop_duplicates()
                .reset_index(drop=True)
            )
        raise ValueError(f"资料缺少必要表头：{'、'.join(columns)}")


def normalize_country(value: object) -> str:
    """采购单中文站点和商品国家使用相同的国家代码匹配。"""
    name = text(value).removesuffix("站")
    return DEFAULT_COUNTRIES.get(name, name.upper())


def read_purchase_products(path: Path) -> pd.DataFrame:
    """复用商品读取，采购额外要求国家、MSKU，按实际命中检查完整性和唯一性。"""
    products = read_product_workbook(path)
    missing = [column for column in PURCHASE_PRODUCT_COLUMNS if column not in products]
    if missing:
        raise ValueError(f"商品信息用于采购单录入时缺少必要字段：{'、'.join(missing)}")
    frame = products[PURCHASE_PRODUCT_COLUMNS].copy()
    for column in PURCHASE_PRODUCT_COLUMNS:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    frame["国家"] = frame["国家"].map(normalize_country)
    return frame.drop_duplicates().reset_index(drop=True)


def read_warehouse_frame(path: Path) -> pd.DataFrame:
    """读取规范仓库表或附件 O:P。"""
    return _read_table(path, WAREHOUSE_COLUMNS, 15, 16)


def validate_warehouses(path: Path) -> None:
    """校验 SKU 仓库资料结构。"""
    read_warehouse_frame(path)


def unique_value(
    frame: pd.DataFrame, sku: str, country: str | None = None
) -> tuple[str, ...]:
    """只允许命中的 SKU、国家对应唯一输出，不猜测多候选。"""
    matches = frame[frame["SKU"].eq(sku)]
    columns = ["仓库"]
    label = "仓库"
    if country is not None:
        matches = matches[matches["国家"].eq(country)]
        columns = ["店铺/站点", "MSKU"]
        label = f"{country}商品信息"
    values = matches[columns].drop_duplicates()
    if values.empty:
        raise ValueError(f"SKU {sku} 缺少{label}")
    missing = [column for column in columns if values[column].eq("").any()]
    if missing:
        raise ValueError(f"SKU {sku} 的{label}缺少字段：{'、'.join(missing)}")
    if len(values) != 1:
        raise ValueError(f"SKU {sku} 的{label}存在多个候选，无法唯一匹配")
    return tuple(str(value) for value in values.iloc[0])
