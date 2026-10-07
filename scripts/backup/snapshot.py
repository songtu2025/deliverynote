"""保存单次备份的快照证据与私有工作目录。"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import tempfile

from scripts.backup.resources import ResourceContext, ResourceReport
from scripts.backup.runtime import BackupConfig, BackupError


@dataclass
class Snapshot:
    directory: Path
    started_at: datetime
    source_counts: dict[str, int] = field(default_factory=dict)
    restored_counts: dict[str, int] = field(default_factory=dict)
    archive_entries: int = 0
    archive_files: int = 0
    resource_context: ResourceContext | None = None
    resource_references: list[tuple[str, str]] = field(default_factory=list)
    source_resources: ResourceReport = field(default_factory=dict)
    restored_resources: ResourceReport = field(default_factory=dict)

    @property
    def database_path(self) -> Path:
        return self.directory / "database.dump"

    @property
    def archive_path(self) -> Path:
        return self.directory / "delivery_data.tar.gz"


def prepare_snapshot(config: BackupConfig, started_at: datetime) -> Snapshot:
    config.destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.destination.chmod(0o700)
    backup_name = started_at.strftime("%Y%m%d-%H%M%S")
    if (config.destination / backup_name).exists():
        raise BackupError(f"目标备份目录已存在：{config.destination / backup_name}")
    directory = Path(
        tempfile.mkdtemp(prefix=f".incomplete-{backup_name}-", dir=config.destination)
    )
    directory.chmod(0o700)
    return Snapshot(directory, started_at)
