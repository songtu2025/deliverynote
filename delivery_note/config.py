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


def supplier_aliases(value: object) -> list[str]:
    """解析以竖线分隔的供应商别名。"""
    if value is None or bool(pd.isna(value)):
        return []
    return [alias.strip() for alias in str(value).split("|") if alias.strip()]


def _supplier_identifiers(row: pd.Series) -> list[str]:
    identifiers = [str(row["供应商名称"]).strip()]
    if "供应商别名" in row.index:
        identifiers.extend(supplier_aliases(row["供应商别名"]))
    return list(dict.fromkeys(identifier for identifier in identifiers if identifier))


def validate_supplier_frame(supplier_rows: pd.DataFrame) -> list[dict]:
    """检查启用供应商之间会造成文件名子串匹配歧义的标识。"""
    required = {"供应商编号", "供应商名称", "状态"}
    missing = sorted(required - set(supplier_rows.columns))
    if missing:
        raise ValueError(f"供应商资料缺少必要字段：{', '.join(missing)}")

    enabled_rows: list[tuple[int, str, str, list[tuple[str, str]]]] = []
    for row_number, (_, row) in enumerate(supplier_rows.iterrows(), start=2):
        if str(row["状态"]).strip() != "启用":
            continue
        code = str(row["供应商编号"]).strip()
        name = str(row["供应商名称"]).strip()
        identifiers = [
            (identifier, _supplier_key(identifier))
            for identifier in _supplier_identifiers(row)
            if _supplier_key(identifier)
        ]
        enabled_rows.append((row_number, code, name, identifiers))

    issues = []
    for index, left in enumerate(enabled_rows):
        left_row, left_code, left_name, left_identifiers = left
        for right in enabled_rows[index + 1 :]:
            right_row, right_code, right_name, right_identifiers = right
            if left_code and left_code == right_code:
                continue
            conflicts = {
                (left_value, right_value)
                for left_value, left_key in left_identifiers
                for right_value, right_key in right_identifiers
                if left_key in right_key or right_key in left_key
            }
            if not conflicts:
                continue
            conflict_text = "、".join(
                f"{left_value} / {right_value}"
                for left_value, right_value in sorted(conflicts)
            )
            issues.append(
                {
                    "severity": "error",
                    "code": "supplier_identifier_conflict",
                    "message": (
                        f"供应商 {left_name} 与 {right_name} 的名称或别名"
                        "会造成匹配歧义："
                        f"{conflict_text}"
                    ),
                    "row_numbers": [left_row, right_row],
                }
            )
    return issues


def resolve_supplier(
    delivery_path: Path, supplier_rows: pd.DataFrame
) -> SupplierIdentity:
    """将文件名转为拼音，与启用的供应商英文名称动态匹配。"""
    required = {"供应商编号", "供应商名称", "状态"}
    missing = sorted(required - set(supplier_rows.columns))
    if missing:
        raise ValueError(f"供应商资料缺少必要字段：{', '.join(missing)}")

    filename_key = _supplier_key(delivery_path.stem)
    enabled = supplier_rows[supplier_rows["状态"].astype(str).str.strip().eq("启用")]
    matches: dict[tuple[str, str], SupplierIdentity] = {}
    for _, row in enabled.iterrows():
        name = str(row["供应商名称"]).strip()
        code = str(row["供应商编号"]).strip()
        identifier_keys = {
            _supplier_key(identifier) for identifier in _supplier_identifiers(row)
        }
        if any(key and key in filename_key for key in identifier_keys):
            matches.setdefault((code, name), SupplierIdentity(name=name, code=code))

    if not matches:
        raise ValueError(f"无法从文件名识别供应商：{delivery_path.name}")
    if len(matches) > 1:
        suppliers = "、".join(
            f"{supplier.name}（{supplier.code}）" for supplier in matches.values()
        )
        raise ValueError(
            f"文件名匹配到多个供应商：{suppliers}；文件：{delivery_path.name}"
        )
    return next(iter(matches.values()))


def _delivery_date(delivery_path: Path) -> str:
    match = re.match(r"^(\d{6})", delivery_path.stem)
    if not match:
        raise ValueError(f"交货单文件名缺少 6 位日期：{delivery_path.name}")
    return match.group(1)


def _supplier_display_name(delivery_path: Path, supplier: SupplierIdentity) -> str:
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
    carton_match = re.search(r"(?:发货|交货)\s*(\d+)\s*箱", delivery_path.stem)
    if not carton_match:
        raise ValueError(f"交货单文件名缺少箱数：{delivery_path.name}")

    supplier_display = _supplier_display_name(delivery_path, supplier)
    cartons = int(carton_match.group(1))
    return f"{delivery_date}-{supplier_display}-{sequence:02d}-{cartons}箱"


def build_document_note(delivery_path: Path, supplier_rows: pd.DataFrame) -> str:
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
