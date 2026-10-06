"""观察真实备份命令，确认快照只在隔离任务排空后开始。"""

from typing import BinaryIO, Sequence

from scripts.backup.runtime import SubprocessRunner
from scripts.backup.services import active_job_count
from tests.support.worker_docker import WorkerDockerFixture


class DrainRunner(SubprocessRunner):
    def __init__(self, fixture: WorkerDockerFixture) -> None:
        self.fixture = fixture
        self.snapshot_counts: list[int] = []
        self.stopped_workers: list[str] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        timeout_seconds: int = 300,
    ) -> str:
        if "pg_dump" in arguments:
            self.snapshot_counts.append(active_job_count(self.fixture.config, self))
        if "stop" in arguments:
            self.stopped_workers.extend(
                service
                for service in arguments
                if service in {"worker", "purchase-sync-worker", "inbound-sync-worker"}
            )
        return super().run(
            arguments, stdin=stdin, stdout=stdout, timeout_seconds=timeout_seconds
        )
