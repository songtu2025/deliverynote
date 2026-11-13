"""采购转换结果及界面预览。"""

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby


@dataclass(frozen=True)
class PurchaseRow:
    order_number: str
    source_site: str
    sku: str
    site: str
    msku: str
    warehouse: str
    quantity: int
    unit_price: Decimal
    delivery_date: date
    note: str


@dataclass(frozen=True)
class PurchaseConversion:
    supplier_code: str
    order_prefix: str
    rows: tuple[PurchaseRow, ...]
    skipped_zero_count: int

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def batch_count(self) -> int:
        return len({row.order_number for row in self.rows})

    @property
    def total_quantity(self) -> int:
        return sum(row.quantity for row in self.rows)

    def to_preview(self) -> dict[str, object]:
        """按原日期列顺序汇总，数值和日期可直接作为 JSON。"""
        batches = []
        for order_number, group in groupby(self.rows, lambda row: row.order_number):
            rows = list(group)
            batches.append(
                {
                    "order_number": order_number,
                    "source_site": rows[0].source_site,
                    "delivery_date": rows[0].delivery_date.isoformat(),
                    "row_count": len(rows),
                    "total_quantity": sum(row.quantity for row in rows),
                }
            )
        preview = []
        for row in self.rows[:20]:
            item = asdict(row)
            item.pop("source_site")
            item["unit_price"] = str(row.unit_price)
            item["delivery_date"] = row.delivery_date.isoformat()
            preview.append(item)
        return {
            "supplier_code": self.supplier_code,
            "order_prefix": self.order_prefix,
            "row_count": self.row_count,
            "batch_count": self.batch_count,
            "total_quantity": self.total_quantity,
            "skipped_zero_count": self.skipped_zero_count,
            "batches": batches,
            "preview": preview,
        }
