from dataclasses import dataclass
from typing import Any, Iterable

from ..processing.keys import _normalize_position_text as key


@dataclass
class TargetedAllowance:
    supplier_code: str
    sku: str
    full_site: str
    inbound_no: str
    po_code: str
    remaining: int
    reason: str = ""


def allocate_targeted(
    records: Iterable[dict[str, Any]],
    allowances: Iterable[TargetedAllowance],
    remaining: int,
) -> int:
    allocated = 0
    for record in records:
        for allowance in allowances:
            if (key(record["入库单号"]), key(record["关联采购单"])) != (
                key(allowance.inbound_no),
                key(allowance.po_code),
            ):
                continue
            quantity = min(remaining, allowance.remaining)
            if quantity <= 0:
                continue
            record["追加超收数量"] += quantity
            record["本次入库"] += quantity
            reason = f"（{allowance.reason}）" if allowance.reason else ""
            note = f"追加超收：{record['追加超收数量']}{reason}"
            rule = record["规则内超收数量"]
            record["超收原因"] = f"规则允许超收：{rule}；{note}" if rule else note
            allowance.remaining -= quantity
            remaining -= quantity
            allocated += quantity
    return allocated
