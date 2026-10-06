"""让真实同步 Worker 访问各自隔离网络中的 ERP 桩。"""

import json
from pathlib import Path
from typing import Any

from tests.support.business_docker import BusinessDockerFixture
from tests.test_purchase_sync import SelfOperatedInboundMappingTests


class ApiDockerFixture(BusinessDockerFixture):
    def prepare(self) -> None:
        stub = self.root / "stub"
        stub.mkdir()
        (stub / "server.py").write_text(
            Path(__file__).with_name("erp_stub.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.set_case(10)
        super().prepare()

    def set_case(
        self,
        quantity: int,
        *,
        warning: bool = False,
        blocked: bool = False,
        fail: bool = False,
    ) -> None:
        # 复用映射测试的接口样本，只调整本演练所需的数量和匹配键。
        order = SelfOperatedInboundMappingTests.order()
        order.update(
            orderNo="IN-S",
            purchaseCode="PO-20260801-AMAZON:SEEKWAY:US",
            releatedCode="LN2608179025",
        )
        detail = order["orderItemResultList"][0]
        detail.update(arriveNum=quantity, maxReceiveNum=quantity + 5)
        if blocked:
            detail["sku"] = ""
        rows = [order]
        if warning:
            shared = SelfOperatedInboundMappingTests.order(site="共享")
            shared["orderNo"] = "IN-SHARED"
            rows.append(shared)
        self._write_case({"rows": rows, "fail": fail})

    def _write_case(self, case: dict[str, Any]) -> None:
        path = self.root / "stub" / "case.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(case), encoding="utf-8")
        temporary.replace(path)

    def _configuration(self, backend_image: str, port: int) -> dict[str, Any]:
        document = super()._configuration(backend_image, port)
        document["services"]["erp-stub"] = {
            "image": self.api_image,
            "command": ["python", "/stub/server.py"],
            "volumes": [f"{self.root / 'stub'}:/stub:ro"],
            "healthcheck": document["services"]["api"]["healthcheck"],
        }
        document["services"]["api"]["depends_on"]["erp-stub"] = {
            "condition": "service_healthy"
        }
        return document

    def remove_restored_candidate(self, job_id: int) -> None:
        if not self.restore_target:
            raise ValueError("故障注入仅允许独立恢复目标")
        path = self.database_query(
            "SELECT v.storage_path FROM input_versions v "
            "JOIN self_operated_inbound_sync_jobs j ON j.candidate_version_id=v.id "
            f"WHERE j.id={job_id} AND v.kind='self_operated_inbound' AND NOT v.active"
        )
        self.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            f"from pathlib import Path; p=Path({path!r}); "
            "assert p.is_relative_to('/data/storage/master/self_operated_inbound'); "
            "p.unlink()",
        )
