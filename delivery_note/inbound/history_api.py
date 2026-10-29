"""共享的入库分页读取，累计核对按关联单号覆盖全部历史状态。"""

from typing import Any


def _validate_page(rows, bill_codes, total, expected_total, scope_count) -> None:
    if any(str(row.get("releatedCode")) not in bill_codes for row in rows):
        raise ValueError("入库接口返回了请求范围外的单据，已停止核对")
    if expected_total is not None and total != expected_total:
        raise ValueError("入库接口分页总数变化，请重新取数")
    if scope_count > total or (not rows and scope_count < total):
        raise ValueError("入库接口分页不完整，请重新取数")


def _check_order_ids(rows, seen) -> None:
    keys = [str(row.get("id") or "") for row in rows]
    if "" in keys or len(set(keys)) != len(keys) or seen.intersection(keys):
        raise ValueError("入库接口分页明细缺少标识或重复，请重新取数")
    seen.update(keys)


def list_inbound_orders(
    client: Any, bill_codes: list[str] | None
) -> list[dict[str, Any]]:
    if not client.access_token:
        client.authenticate()
    orders: list[dict[str, Any]] = []
    scopes = (
        [
            (str(warehouse), kind)
            for warehouse in (0, 1, 3, 4)
            for kind in ("purchase", "transfer")
        ]
        if bill_codes is not None
        else [("0", "purchase"), ("1", "transfer")]
    )
    for rn_type, order_type in scopes:
        page = 1
        scope_count = 0
        expected_total = None
        seen: set[str] = set()
        while True:
            filters = (
                {"billType": "3", "billCodes": bill_codes}
                if bill_codes is not None
                else {}
            )
            response = client._request(
                "/fulfillment/store/selfInboundListAndDetail/page",
                {
                    "rnType": rn_type,
                    "orderType": order_type,
                    "orderStatusList": [
                        "WAIT_INBOUND",
                        "PART_INBOUND",
                        "COMPLETED",
                        "CANCELLED",
                    ]
                    if bill_codes is not None
                    else ["WAIT_INBOUND", "PART_INBOUND"],
                    **filters,
                    "page": page,
                    "pagesize": 500,
                },
                group=f"self-operated-inbound-list-{order_type}",
                interval=0.5,
            )
            data = response.get("data") or {}
            rows = data.get("rows") or []
            total = int(data.get("total") or 0)
            scope_count += len(rows)
            if bill_codes is not None:
                _validate_page(rows, bill_codes, total, expected_total, scope_count)
                _check_order_ids(rows, seen)
                expected_total = total
                for row in rows:
                    row["_receipt_rn_type"] = rn_type
            orders.extend(rows)
            if scope_count >= total:
                break
            page += 1
    return orders
