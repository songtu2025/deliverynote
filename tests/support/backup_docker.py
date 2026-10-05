"""复用发布演练环境，增加真实 PostgreSQL 和独立业务文件卷。"""

import json
from pathlib import Path
import subprocess
from typing import Any

from scripts.backup.runtime import BackupConfig
from tests.support.release_docker import ReleaseDockerFixture


FILES = {
    "storage/input.bin": b"input-data\x00\xff",
    "storage/batch.bin": b"batch-data\n",
    "storage/empty.bin": b"",
    "exports/result.bin": b"export-data\x00\xff",
}


SEED = """
import os
from pathlib import Path
from delivery_note.web.database import Database
from delivery_note.web.models import (
    User, InputVersion, Batch, BatchFile, Job,
    PurchaseSyncJob, SelfOperatedInboundSyncJob,
)
for name, content in {files}.items():
    target = Path('/data') / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
database = Database(os.environ['DATABASE_URL'])
try:
    with database.session() as session:
        user = User(username='backup-test', password_hash='test-only')
        session.add(user)
        session.flush()
        versions = {{}}
        for kind in ('product', 'supplier'):
            version = InputVersion(kind=kind, name=kind, original_name=kind+'.bin',
                storage_path='/data/storage/input.bin', created_by=user.id)
            session.add(version)
            session.flush()
            versions[kind] = version.id
        batch = Batch(name='备份演练', created_by=user.id,
            product_version_id=versions['product'],
            supplier_version_id=versions['supplier'])
        session.add(batch)
        session.flush()
        session.add_all([
            BatchFile(batch_id=batch.id, original_name='batch.bin', file_order=1,
                storage_path='/data/storage/batch.bin',
                result_path='/data/exports/result.bin'),
            Job(batch_id=batch.id, kind='compute', status='succeeded',
                output_path='/data/exports/result.bin'),
            PurchaseSyncJob(created_by=user.id, status='succeeded'),
            SelfOperatedInboundSyncJob(created_by=user.id, status='succeeded'),
        ])
        session.commit()
finally:
    database.dispose()
"""


class BackupDockerFixture(ReleaseDockerFixture):
    def __init__(self, web_image: str, api_image: str) -> None:
        super().__init__(web_image)
        self.api_image = api_image
        self.volume = self.project + "_delivery_data"
        self.config = BackupConfig(
            compose_file=self.compose_file,
            env_file=self.env_file,
            project_name=self.project,
            destination=self.root / "backups",
            lock_file=self.root / "backup.lock",
            stop_timeout_seconds=2,
            service_wait_timeout_seconds=30,
        )

    def start(self) -> None:
        super().start()
        self.compose("exec", "-T", "api", "python", "-m", "delivery_note.migrations")
        self.compose(
            "exec", "-T", "api", "python", "-c", SEED.format(files=repr(FILES))
        )

    def _configuration(self, backend_image: str, port: int) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[2]
        configuration = json.loads(
            self.run(
                "docker",
                "compose",
                "--file",
                str(root / "compose.yaml"),
                "--env-file",
                str(root / ".env.example"),
                "config",
                "--format",
                "json",
            )
        )
        document = super()._configuration(backend_image, port)
        document["services"]["db"] = {
            "image": configuration["services"]["db"]["image"],
            "environment": {
                "POSTGRES_DB": "delivery_note",
                "POSTGRES_USER": "delivery_note",
                "POSTGRES_PASSWORD": "backup-test-password",
            },
            "tmpfs": ["/var/lib/postgresql/data"],
            "healthcheck": {
                "test": [
                    "CMD",
                    "pg_isready",
                    "-U",
                    "delivery_note",
                    "-d",
                    "delivery_note",
                ],
                "interval": "1s",
                "timeout": "5s",
                "retries": 30,
            },
        }
        api = document["services"]["api"]
        api["image"] = self.api_image
        api["volumes"] = ["delivery_data:/data"]
        api["environment"] = {
            "DATABASE_URL": "postgresql+psycopg://delivery_note:backup-test-password@db:5432/delivery_note"
        }
        api["depends_on"] = {"db": {"condition": "service_healthy"}}
        document["volumes"] = {"delivery_data": {}}
        return document

    def database_query(self, query: str, database: str = "delivery_note") -> str:
        return self.compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "delivery_note",
            "-d",
            database,
            "-Atq",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            query,
        )

    def close(self) -> None:
        try:
            super().close()
        finally:
            # 卷名称来自本测试随机项目名，正式卷不在清理范围。
            subprocess.run(
                ["docker", "volume", "rm", self.volume],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
