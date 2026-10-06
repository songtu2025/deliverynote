"""交货和自营仓演练共用真实服务与空恢复目标。"""

import os
import unittest

from tests.support.business_docker import BusinessDockerFixture


class RecoveryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = BusinessDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"], os.environ["BACKUP_API_IMAGE"]
        )
        self.addCleanup(self.fixture.close)
        self.fixture.start()

    def empty_target(self) -> BusinessDockerFixture:
        target = BusinessDockerFixture(
            os.environ["RELEASE_WEB_IMAGE"],
            os.environ["BACKUP_API_IMAGE"],
            restore_target=True,
        )
        self.addCleanup(target.close)
        target.start()
        self.assertEqual(
            target.database_query(
                "SELECT datname FROM pg_database WHERE datname='delivery_note'",
                "postgres",
            ),
            "",
        )
        self.assertEqual(
            target.compose("ps", "--status", "running", "--services"), "db"
        )
        return target
