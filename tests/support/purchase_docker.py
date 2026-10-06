"""在现有隔离 ERP 桩中提供采购分页及详情数据。"""

import json
from typing import Any

from tests.support.api_docker import ApiDockerFixture
from tests.test_purchase_sync import PurchaseMappingTests


class PurchaseDockerFixture(ApiDockerFixture):
    def set_case(
        self,
        quantity: int,
        *,
        warning: bool = False,
        blocked: bool = False,
        fail: bool = False,
        fingerprint: int | None = None,
    ) -> None:
        orders = []
        details = {}
        # 六张单可观察到至少一次缓存命中，第六张零余额验证过滤。
        for index in range(6):
            code = f"PO-{index + 1}"
            orders.append(
                {
                    "code": code,
                    "invoicesStatusName": "待交货",
                    "revision": quantity if fingerprint is None else fingerprint,
                }
            )
            details[code] = PurchaseMappingTests.detail(
                balance=quantity // 5 if index < 5 else 0
            )
        if blocked:
            orders[0]["revision"] = "blocked"
            details["PO-1"]["warehouseProcureItemVos"][0]["procureItemVos"][0][
                "product"
            ] = ""
        if warning:
            orders.append({"code": "PO-SHARED", "invoicesStatusName": "待交货"})
            details["PO-SHARED"] = PurchaseMappingTests.detail(balance=10, site="共享")
        self._write_case({"orders": orders, "details": details, "fail": fail})

    def requests(self) -> list[dict[str, Any]]:
        payload = self.compose("exec", "-T", "erp-stub", "cat", "/tmp/requests.jsonl")
        return [json.loads(line) for line in payload.splitlines()]

    def cache(self) -> str:
        return self.compose(
            "exec", "-T", "api", "cat", "/data/storage/cache/purchase-details-v1.json"
        )
