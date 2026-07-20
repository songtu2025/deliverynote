from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd
from pypinyin import lazy_pinyin


@dataclass(frozen=True)
class SupplierIdentity:
    name: str
    code: str

PURCHASE_STATUSES = ("交货中", "待交货")

WAREHOUSE_PRIORITY = {
    "供应商成品本地仓": 0,
}


def _supplier_key(value: object) -> str:
    pinyin = "".join(lazy_pinyin(str(value))).lower()
    return re.sub(r"[^a-z0-9]", "", pinyin)


def resolve_supplier(
    delivery_path: Path, supplier_rows: pd.DataFrame
) -> SupplierIdentity:
    """将文件名转为拼音，与启用的供应商英文名称动态匹配。"""
    required = {"供应商编号", "供应商名称", "状态"}
    missing = sorted(required - set(supplier_rows.columns))
    if missing:
        raise ValueError(f"供应商资料缺少必要字段：{', '.join(missing)}")

    filename_key = _supplier_key(delivery_path.stem)
    enabled = supplier_rows[
        supplier_rows["状态"].astype(str).str.strip().eq("启用")
    ]
    matches = []
    for _, row in enabled.iterrows():
        name = str(row["供应商名称"]).strip()
        code = str(row["供应商编号"]).strip()
        name_key = _supplier_key(name)
        if name_key and name_key in filename_key:
            matches.append(SupplierIdentity(name=name, code=code))

    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise ValueError(f"无法从文件名识别供应商：{delivery_path.name}")
    return matches[0]


def _delivery_date(delivery_path: Path) -> str:
    match = re.match(r"^(\d{6})", delivery_path.stem)
    if not match:
        raise ValueError(f"交货单文件名缺少 6 位日期：{delivery_path.name}")
    return match.group(1)


def _supplier_display_name(
    delivery_path: Path, supplier: SupplierIdentity
) -> str:
    filename_body = re.sub(r"^\d{6}[\s_-]*", "", delivery_path.stem)
    supplier_key = _supplier_key(supplier.name)
    display_chars: list[str] = []
    accumulated_key = ""

    for character in filename_body:
        character_key = _supplier_key(character)
        if not character_key:
            continue
        display_chars.append(character)
        accumulated_key += character_key
        if supplier_key in accumulated_key:
            return "".join(display_chars).strip(" -_")
        if not supplier_key.startswith(accumulated_key):
            break

    return re.sub(r"\s+", "", supplier.name)


def build_ordered_document_note(
    delivery_path: Path,
    supplier: SupplierIdentity,
    sequence: int,
) -> str:
    """按明确的文件顺序生成“日期-供应商-序号-箱数”备注。"""
    if sequence <= 0:
        raise ValueError("交货单顺序必须大于 0")
    delivery_date = _delivery_date(delivery_path)
    carton_match = re.search(
        r"(?:发货|交货)\s*(\d+)\s*箱", delivery_path.stem
    )
    if not carton_match:
        raise ValueError(f"交货单文件名缺少箱数：{delivery_path.name}")

    supplier_display = _supplier_display_name(delivery_path, supplier)
    cartons = int(carton_match.group(1))
    return f"{delivery_date}-{supplier_display}-{sequence:02d}-{cartons}箱"


def build_document_note(
    delivery_path: Path, supplier_rows: pd.DataFrame
) -> str:
    """兼容 CLI：从同目录文件推导顺序，再调用统一备注生成函数。"""
    delivery_date = _delivery_date(delivery_path)
    supplier = resolve_supplier(delivery_path, supplier_rows)

    peer_files: list[Path] = []
    for candidate in delivery_path.parent.iterdir():
        if not candidate.is_file() or candidate.suffix.lower() not in {".xls", ".xlsx"}:
            continue
        try:
            same_date = _delivery_date(candidate) == delivery_date
            same_supplier = (
                resolve_supplier(candidate, supplier_rows).code == supplier.code
            )
        except ValueError:
            continue
        if same_date and same_supplier:
            peer_files.append(candidate)

    peer_files.sort(key=lambda path: path.name.casefold())
    sequence = [path.name for path in peer_files].index(delivery_path.name) + 1
    return build_ordered_document_note(delivery_path, supplier, sequence)


def warehouse_sort_key(warehouse: str) -> tuple[int, str]:
    """供应商成品本地仓优先，其余仓库按名称保持稳定顺序。"""
    return WAREHOUSE_PRIORITY.get(warehouse, 1), warehouse
