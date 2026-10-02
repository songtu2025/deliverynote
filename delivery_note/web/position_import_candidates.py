from _thread import LockType
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass
class PositionImportCandidates:
    """单个接口进程内的导入预览令牌及对应临时文件。"""

    root: Path
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: LockType = field(default_factory=Lock)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def peek(self, token: str) -> dict[str, Any] | None:
        with self.lock:
            return self.entries.get(token)

    def take(self, token: str) -> dict[str, Any] | None:
        with self.lock:
            return self.entries.pop(token, None)

    def remove(self, token: str) -> dict[str, Any] | None:
        candidate = self.take(token)
        if candidate is not None:
            Path(candidate["path"]).unlink(missing_ok=True)
        return candidate

    def register(self, token: str, candidate: dict[str, Any]) -> None:
        with self.lock:
            self.entries[token] = candidate

    def remove_draft(self, draft_id: int) -> None:
        with self.lock:
            tokens = [
                token
                for token, candidate in self.entries.items()
                if candidate["draft_id"] == draft_id
            ]
        for token in tokens:
            self.remove(token)

    def remove_expired(self, ttl_seconds: int) -> None:
        now = datetime.utcnow()
        with self.lock:
            expired = [
                (token, self.entries.pop(token))
                for token in list(self.entries)
                if self.entries[token]["expires_at"] <= now
            ]
        for _token, candidate in expired:
            Path(candidate["path"]).unlink(missing_ok=True)
        expiry_cutoff = datetime.now().timestamp() - ttl_seconds
        with self.lock:
            registered_paths = {
                Path(candidate["path"]).resolve() for candidate in self.entries.values()
            }
        for candidate_path in self.root.iterdir():
            if (
                candidate_path.is_file()
                and candidate_path.resolve() not in registered_paths
                and candidate_path.stat().st_mtime <= expiry_cutoff
            ):
                candidate_path.unlink(missing_ok=True)
