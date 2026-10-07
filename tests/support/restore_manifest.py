"""生成恢复预检测试共用的完整备份，不重复业务测试。"""

from contextlib import nullcontext
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class ManifestTestCase(BackupTestCase):
    def setUp(self) -> None:
        super().setUp()
        with patch(
            "scripts.backup.workflow.exclusive_lock", return_value=nullcontext()
        ):
            result = create_backup(
                self.config, runner=FakeRunner(), now=lambda: self.fixed_time
            )
        self.directory = Path(str(result["backup_directory"]))
        self.path = self.directory / "BACKUP-METADATA.json"
        self.metadata: dict[str, Any] = json.loads(
            self.path.read_text(encoding="utf-8")
        )

    def save(self) -> None:
        self.path.write_text(json.dumps(self.metadata), encoding="utf-8")
