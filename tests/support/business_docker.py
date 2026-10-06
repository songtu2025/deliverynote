"""在既有隔离环境中运行真实 API 和三类 Worker。"""

from typing import Any
from pathlib import Path

from tests.support.backup_docker import BackupDockerFixture
from tests.support.release_docker import ReleaseDockerFixture


class BusinessDockerFixture(BackupDockerFixture):
    def __init__(
        self, web_image: str, api_image: str, *, restore_target: bool = False
    ) -> None:
        super().__init__(web_image, api_image)
        self.restore_target = restore_target

    def start(self) -> None:
        # 真实 API 初始化结构和账号，不写入备份模拟数据。
        if self.restore_target:
            self.prepare()
            self.compose("up", "-d", "--wait", "--wait-timeout", "30", "db")
            self.compose("create", "api")
        else:
            ReleaseDockerFixture.start(self)

    def restore_from(self, source: "BusinessDockerFixture", directory: Path) -> None:
        from tests.support.business_restore import restore_business_backup

        restore_business_backup(source, self, directory)
        self.start_services()

    def _configuration(self, backend_image: str, port: int) -> dict[str, Any]:
        document = super()._configuration(backend_image, port)
        api = document["services"]["api"]
        api.pop("command")
        api["environment"].update(
            STORAGE_ROOT="/data/storage",
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="admin-pass",
            SESSION_COOKIE_SECURE="false",
            GERPGO_API_BASE_URL="http://127.0.0.1:9",
            GERPGO_APP_ID="",
            GERPGO_APP_KEY="",
        )
        if self.restore_target:
            database = document["services"]["db"]
            database["environment"]["POSTGRES_DB"] = "postgres"
            database["healthcheck"]["test"][-1] = "postgres"
            api["environment"].update(
                AUTO_MIGRATE_SCHEMA="false",
                ADMIN_PASSWORD="must-not-reset-restored-password",
            )
        for service, queue in (
            ("worker", "batch"),
            ("purchase-sync-worker", "purchase-sync"),
            ("inbound-sync-worker", "inbound-sync"),
        ):
            document["services"][service] = {
                "image": self.api_image,
                "command": [
                    "python",
                    "-m",
                    "delivery_note.worker",
                    "--queue",
                    queue,
                    "--poll-interval",
                    "0.1",
                ],
                "environment": api["environment"],
                "volumes": api["volumes"],
                "depends_on": {"api": {"condition": "service_healthy"}},
            }
        document["services"]["web"]["networks"] = ["default", "entry"]
        document["networks"] = {"default": {"internal": True}, "entry": {}}
        return document
