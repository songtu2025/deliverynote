from enum import StrEnum


class ExceptionReason(StrEnum):
    PRODUCT_NOT_FOUND = "产品信息未匹配"
    AMBIGUOUS_PRODUCT_SITE = "产品信息站点不唯一"
    PURCHASE_BALANCE_EXCEEDED = "超出采购未交量"
    PURCHASE_NOT_FOUND = "未找到可交货采购需求"
    OVERRECEIPT_LIMIT_EXCEEDED = "超出允许超收量"
    INBOUND_ORDER_NOT_FOUND = "未找到自营仓入库单"
    SUPPLIER_MISMATCH = "供应商不一致"
    PO_NAME_MISSING = "PO名称为空"
    RECEIVABLE_INVALID = "应收货无效"
    RECEIVABLE_EXCEEDED = "超出应收货"


def exception_reason_code(reason: str) -> str:
    try:
        return ExceptionReason(reason).name.lower()
    except ValueError:
        return "unknown"
