import os
import unittest

from tests.support.business_docker import BusinessDockerFixture
from tests.support.business_scenario import DeliveryScenario
from tests.support.delivery_exports import assert_delivery_exports


@unittest.skipUnless(
    os.environ.get("RECOVERY_BUSINESS_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 业务恢复演练",
)
class RecoveryBusinessDockerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = BusinessDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"], os.environ["BACKUP_API_IMAGE"]
        )
        self.addCleanup(self.fixture.close)
        self.fixture.start()
        self.scenario = DeliveryScenario(self.fixture.url, self.fixture.root)
        self.addCleanup(self.scenario.client.close)

    def test_real_api_and_workers_compute_split_and_export_baseline(self) -> None:
        self.assertEqual(self.scenario.login()["username"], "admin")
        self.scenario.create_baseline()
        batch = self.scenario.batch()
        self.assertEqual(batch["status"], "succeeded")
        self.assertEqual(
            [(item["import_total"], item["manual_total"]) for item in batch["files"]],
            [(80, 0), (20, 60)],
        )
        self.scenario.split_and_export()
        assert_delivery_exports(self, *self.scenario.downloads())
        for service in ("api", "worker", "purchase-sync-worker", "inbound-sync-worker"):
            record = self.fixture.inspect(service)[0]
            self.assertEqual(record["State"]["Status"], "running")
            self.assertEqual(record["RestartCount"], 0)
            command = record["Config"]["Cmd"]
            self.assertIn(
                "delivery_note.web.api:create_app"
                if service == "api"
                else "delivery_note.worker",
                command,
            )
