"""真实导出在文件发布和数据库登记边界中断，保护已有下载。"""

import os
from pathlib import Path
from typing import Any
import unittest

from tests.support.business_case import RecoveryCase
from tests.support.delivery_exports import assert_delivery_exports
from tests.support.inbound_exports import assert_inbound_exports
from tests.support.inbound_scenario import InboundScenario
from tests.support.worker_docker import WorkerDockerFixture, wait_until


@unittest.skipUnless(
    os.getenv("WORKER_DOCKER_TESTS") == "1", "需显式开启隔离 Worker 演练"
)
class ExportPublicationDockerTests(RecoveryCase):
    fixture_type = WorkerDockerFixture
    fixture: WorkerDockerFixture

    def prepare_exports(self, inbound: bool) -> tuple[int, dict[str, Any], int]:
        if inbound:
            self.scenario.client.close()
            self.scenario = InboundScenario(self.fixture.url, self.fixture.root)
            self.addCleanup(self.scenario.client.close)
        self.scenario.login()
        self.scenario.activate_inputs()
        if inbound:
            self.scenario.request(
                "POST",
                "/api/self-operated-overreceipt-rule-versions",
                201,
                json={"name": "发布中断共享超收5件", "allowance": 5},
            )
        self.create_batch()
        self.scenario.export()
        historical_id = self.scenario.batch_id
        historical = self.batch_record()
        self.create_batch()
        identifier = self.scenario.export()
        self.fixture.compose("stop", "-t", "10", "worker")
        return historical_id, historical, identifier

    def create_batch(self) -> None:
        if isinstance(self.scenario, InboundScenario):
            self.scenario.create_inbound_batch(multiple=True)
        else:
            self.scenario.create_delivery_batch()

    def batch_record(self) -> dict[str, Any]:
        identifier = self.scenario.batch_id
        snapshot = self.scenario.snapshot()
        self.scenario.batch_id = identifier
        if isinstance(self.scenario, InboundScenario):
            return dict(snapshot["batches"][identifier])
        return {name: snapshot[name] for name in ("batch", "exceptions", "exports")}

    def registered_paths(self) -> list[str]:
        identifier = self.scenario.batch_id
        return self.fixture.database_query(
            f"SELECT zip_path FROM batches WHERE id={identifier} UNION ALL "
            f"SELECT result_path FROM batch_files WHERE batch_id={identifier} "
            "ORDER BY 1"
        ).splitlines()

    def requeue_export(self, identifier: int) -> Path:
        previous = Path(self.registered_paths()[0]).parent
        merged = previous / f"batch-{self.scenario.batch_id}-merged.xlsx"
        held = merged.with_suffix(".held")
        self.fixture.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            f"from pathlib import Path; Path({str(merged)!r}).rename({str(held)!r})",
        )
        try:
            # 复用合并文件缺失时的真实 API 重排逻辑，随后恢复旧下载。
            self.assertEqual(self.scenario.export(wait=False), identifier)
        finally:
            self.fixture.compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                f"from pathlib import Path; "
                f"Path({str(held)!r}).rename({str(merged)!r})",
            )
        return previous

    def assert_directory(self, path: Path) -> None:
        self.fixture.compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "from pathlib import Path; from zipfile import ZipFile; "
            f"p=Path({str(path)!r}); assert p.is_dir(); "
            f"assert len(list(p.glob('*.xlsx')))==3; "
            f"z=ZipFile(p/'batch-{self.scenario.batch_id}.zip'); "
            "assert len(z.namelist())==2; assert z.testzip() is None; z.close()",
        )

    def assert_recovery(
        self, identifier: int, point: str, marker: dict[str, Any]
    ) -> None:
        fixture = self.fixture
        stopped = fixture.job("export", identifier)
        self.assertEqual(fixture.recover("export"), 0)
        self.assertEqual(fixture.job("export", identifier), stopped)
        if point == "published":
            fixture.expire("export", identifier)
            fixture.arm("export.published")
            fixture.compose("start", "worker")
            replacement = fixture.arrived("export.published")
            self.assertNotEqual(replacement["claim"], marker["claim"])
            retry = fixture.job("export", identifier)
            self.assertEqual((retry["status"], retry["attempts"]), ("running", 3))
            self.assertEqual(retry["claim_token"], replacement["claim"])
        fixture.release("export." + point)
        if point == "registered":
            fixture.compose("start", "worker")
            once = fixture.once("export")
            wait_until(
                lambda: not fixture.state(once)["Running"],
                "成功登记后的领取检查未结束",
            )
            self.assertEqual(fixture.state(once)["ExitCode"], 0)
        wait_until(
            lambda: fixture.job("export", identifier)["status"] == "succeeded",
            "发布中断后的导出未完成登记",
        )
        fixture.compose("stop", "-t", "10", "worker")
        final = fixture.job("export", identifier)
        self.assertEqual(final["attempts"], 3 if point == "published" else 2)
        self.assertIsNone(final["claim_token"])
        self.assertIsNotNone(final["output_path"])
        if point == "registered":
            self.assertEqual(final, stopped)

    def assert_publication(self, inbound: bool, point: str) -> None:
        historical_id, historical, identifier = self.prepare_exports(inbound)
        current_id = self.scenario.batch_id
        old_record = self.batch_record()
        old_downloads = self.scenario.downloads()
        old_paths = self.registered_paths()
        previous = self.requeue_export(identifier)
        fixture = self.fixture
        fixture.arm("export." + point)
        fixture.compose("start", "worker")
        marker = fixture.arrived("export." + point)
        self.assertEqual(marker["id"], identifier)
        published = Path(marker["path"])
        self.assertNotEqual(published, previous)
        self.assert_directory(published)
        self.assert_directory(previous)
        job = fixture.job("export", identifier)
        self.assertEqual(job["attempts"], 2)
        if point == "published":
            self.assertEqual(job["status"], "running")
            self.assertEqual(job["claim_token"], marker["claim"])
            self.assertIsNone(job["output_path"])
            self.assertEqual(self.registered_paths(), old_paths)
            self.assertEqual(self.batch_record()["exports"], old_record["exports"])
            self.assertEqual(self.scenario.downloads(), old_downloads)
        else:
            self.assertEqual(job["status"], "succeeded")
            self.assertIsNone(job["claim_token"])
            self.assertTrue(
                all(Path(p).parent == published for p in self.registered_paths())
            )
        container = fixture.inspect("worker")[0]["Id"]
        fixture.run("docker", "kill", "--signal", "KILL", container)
        self.assertFalse(fixture.state(container)["Running"])
        self.assertEqual(fixture.state(container)["ExitCode"], 137)
        if point == "published":
            self.assertEqual(self.scenario.downloads(), old_downloads)
        self.assert_recovery(identifier, point, marker)
        paths = self.registered_paths()
        final = fixture.job("export", identifier)
        self.assertIn(final["output_path"], paths)
        self.assertTrue(
            all(Path(p).parent == Path(final["output_path"]).parent for p in paths)
        )
        record = self.batch_record()
        if inbound:
            assert_inbound_exports(self, record)
        else:
            assert_delivery_exports(self, *record["exports"], resolved=0)
        action = (
            "worker_self_operated_export_succeeded"
            if inbound
            else "worker_export_succeeded"
        )
        self.assertEqual(
            fixture.database_query(
                f"SELECT count(*) FROM audit_logs WHERE action='{action}' "
                f"AND entity_id='{current_id}'"
            ),
            "2",
        )
        self.scenario.batch_id = historical_id
        self.assertEqual(self.batch_record(), historical)

    def test_delivery_published_directory_recovers(self) -> None:
        self.assert_publication(False, "published")

    def test_delivery_registered_directory_is_not_reclaimed(self) -> None:
        self.assert_publication(False, "registered")

    def test_inbound_published_directory_recovers(self) -> None:
        self.assert_publication(True, "published")

    def test_inbound_registered_directory_is_not_reclaimed(self) -> None:
        self.assert_publication(True, "registered")
