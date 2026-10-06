"""复用业务演练环境，控制真实 Worker 的执行和退出时序。"""

import json
from pathlib import Path
import time
from typing import Any, Callable, cast

from tests.support.api_docker import ApiDockerFixture
from tests.support.purchase_docker import PurchaseDockerFixture


TASKS = {
    "compute": ("worker", "jobs"),
    "export": ("worker", "jobs"),
    "purchase-sync": ("purchase-sync-worker", "purchase_sync_jobs"),
    "inbound-sync": ("inbound-sync-worker", "self_operated_inbound_sync_jobs"),
}


def wait_until(predicate: Callable[[], bool], message: str, seconds: int = 30) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(message)
        time.sleep(0.1)


class WorkerDockerFixture(PurchaseDockerFixture):
    @property
    def control(self) -> Path:
        return self.root / "control"

    def prepare(self) -> None:
        self.control.mkdir()
        source = Path(__file__).with_name("worker_process.py")
        (self.control / source.name).write_bytes(source.read_bytes())
        super().prepare()
        # 同一个桩提供两种同步样本，业务映射仍复用已有测试数据。
        case = json.loads((self.root / "stub" / "case.json").read_text())
        ApiDockerFixture.set_case(self, 10)
        case.update(json.loads((self.root / "stub" / "case.json").read_text()))
        self._write_case(case)

    def _configuration(self, backend_image: str, port: int) -> dict[str, Any]:
        document = super()._configuration(backend_image, port)
        for service in {values[0] for values in TASKS.values()}:
            record = document["services"][service]
            record["command"][:3] = ["python", "/control/worker_process.py"]
            record["environment"] = {
                **record["environment"],
                "WORKER_TEST_CONTROL": "/control",
            }
            record["volumes"] = [*record["volumes"], f"{self.control}:/control"]
        return document

    def arm(self, kind: str) -> None:
        (self.control / (kind + ".arrived")).unlink(missing_ok=True)
        (self.control / (kind + ".hold")).touch()

    def release(self, kind: str) -> None:
        (self.control / (kind + ".hold")).unlink(missing_ok=True)

    def arrived(self, kind: str) -> dict[str, Any]:
        marker = self.control / (kind + ".arrived")
        wait_until(marker.exists, f"任务未进入阻塞点：{kind}")
        result: dict[str, Any] = json.loads(marker.read_text())
        return result

    def job(self, kind: str, identifier: int) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(
            self.database_query(
                f"SELECT row_to_json(t)::text FROM {TASKS[kind][1]} t "
                f"WHERE id={identifier}"
            )
        )
        return result

    def state(self, identifier: str) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.run("docker", "inspect", identifier))[
            0
        ]
        return cast(dict[str, Any], result["State"])

    def close(self) -> None:
        for kind in TASKS:
            self.release(kind)
            self.release(kind + ".finalize")
        super().close()

    def recover(self, kind: str) -> int:
        queue = "batch" if TASKS[kind][0] == "worker" else kind
        return int(
            self.compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import os; from delivery_note.worker import recover_stale_jobs; "
                "print(recover_stale_jobs(os.environ['DATABASE_URL'], "
                f"queue={queue!r}))",
            )
        )

    def expire(self, kind: str, identifier: int) -> None:
        # 只推进随机测试项目中的任务时钟，不修改正式租约时长。
        self.database_query(
            f"UPDATE {TASKS[kind][1]} SET heartbeat_at=NOW()-INTERVAL '2 hours' "
            f"WHERE id={identifier} AND status='running'"
        )
