"""为隔离与恢复测试复用真实存储引用和混合导出目录。"""

from pathlib import Path

from scripts.backup.archive import sha256
from scripts.storage_quarantine import prepare_quarantine, transition_quarantine
from tests.support.storage_audit import StorageAuditCase


class StorageQuarantineCase(StorageAuditCase):
    def setUp(self) -> None:
        super().setUp()
        self.current = self.seed_outputs()
        self.old = self.storage / (f"batches/{self.batch_id}/exports/export-{'b' * 32}")
        self.file(str(self.old.relative_to(self.storage) / "旧结果.xlsx"))
        self.file(str(self.old.relative_to(self.storage) / "旧归档.zip"))
        self.extra = [
            self.file(str(self.current.relative_to(self.storage) / name))
            for name in ("旧合并.xlsx", "旧完整.zip")
        ]
        self.file("cache/inspection.json")
        self.quarantine_dir = self.root / "quarantine" / "run-1"
        self.paths = [
            str(path.relative_to(self.storage)) for path in (self.old, *self.extra)
        ]
        self.database_file = Path(self.app.state.database.engine.url.database)

    def prepare(self):
        return prepare_quarantine(
            self.url, self.storage, self.paths, self.quarantine_dir
        )

    def apply(self, restore: bool = False):
        return transition_quarantine(
            self.url, self.storage, self.quarantine_dir, restore=restore
        )

    def contents(self):
        return {
            str(path.relative_to(self.storage)): sha256(path)
            for path in self.storage.rglob("*")
            if path.is_file()
        }
