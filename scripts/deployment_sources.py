"""比较后端容器源码、依赖与镜像标记的确切 Git 提交。"""

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
from typing import cast

from scripts.backup.runtime import BackupError, Runner


REVISION_LABEL = "org.opencontainers.image.revision"
BACKEND_SERVICES = frozenset(
    {"api", "worker", "purchase-sync-worker", "inbound-sync-worker"}
)

RUNTIME_PROBE = """
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path

root = Path('/app')
paths = [path for path in (root / 'delivery_note').rglob('*')
         if path.is_file() and '__pycache__' not in path.parts]
lock = root / 'requirements.lock'
if lock.is_file():
    paths.append(lock)
hashes = {
    path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in paths
}
versions = {item.metadata['Name'].lower().replace('_', '-'): item.version
            for item in distributions() if item.metadata['Name']}
print(json.dumps({'files': hashes, 'versions': versions}))
"""


def source_files(
    root: Path, revision: str, runner: Runner
) -> tuple[dict[str, str], dict[str, str]]:
    hashes = {}
    dependencies = {}
    with tempfile.TemporaryFile() as archive:
        runner.run(
            [
                "git",
                "-C",
                str(root),
                "archive",
                revision,
                "delivery_note",
                "requirements.lock",
            ],
            stdout=archive,
        )
        archive.seek(0)
        with tarfile.open(fileobj=archive) as handle:
            for member in handle:
                if not member.isfile():
                    continue
                stream = handle.extractfile(member)
                if stream is None:
                    raise BackupError(f"无法读取提交文件：{member.name}")
                content = stream.read()
                hashes[member.name] = hashlib.sha256(content).hexdigest()
                if member.name == "requirements.lock":
                    dependencies = {
                        name.lower().replace("_", "-"): version
                        for line in content.decode().splitlines()
                        if "==" in line
                        for name, version in [line.split("==", 1)]
                    }
    if "requirements.lock" not in hashes or not any(
        name.startswith("delivery_note/") for name in hashes
    ):
        raise BackupError("提交缺少后端源码或依赖锁文件")
    return hashes, dependencies


def verify_backend_source(
    root: Path, container: str, revision: str, target: str, runner: Runner
) -> dict[str, object]:
    probe = cast(
        dict[str, dict[str, str]],
        json.loads(
            runner.run(["docker", "exec", container, "python", "-c", RUNTIME_PROBE])
        ),
    )
    return _verify_probe(root, revision, target, runner, probe)


def verify_backend_image(
    root: Path, image: str, revision: str, runner: Runner
) -> dict[str, object]:
    probe = cast(
        dict[str, dict[str, str]],
        json.loads(
            runner.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--read-only",
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    RUNTIME_PROBE,
                ]
            )
        ),
    )
    return _verify_probe(root, revision, revision, runner, probe)


def _verify_probe(
    root: Path,
    revision: str,
    target: str,
    runner: Runner,
    probe: dict[str, dict[str, str]],
) -> dict[str, object]:
    expected, dependencies = source_files(root, revision, runner)
    actual = probe["files"]
    different = sorted(
        name
        for name in set(expected) | set(actual)
        if expected.get(name) != actual.get(name)
    )
    if different:
        raise BackupError("运行源码与镜像标记提交不一致：" + ", ".join(different))
    mismatched = sorted(
        name
        for name, version in dependencies.items()
        if probe["versions"].get(name) != version
    )
    if mismatched:
        raise BackupError("运行依赖与提交锁定版本不一致：" + ", ".join(mismatched))
    latest, _ = source_files(root, target, runner)
    return {
        "source_files": len(expected),
        "source_matches_revision": True,
        "dependencies_match_lock": True,
        "different_from_target": sorted(
            name
            for name in set(latest) | set(actual)
            if latest.get(name) != actual.get(name)
        ),
    }


def verify_schema_unchanged(
    root: Path, revision: str, target: str, runner: Runner
) -> None:
    old, _ = source_files(root, revision, runner)
    new, _ = source_files(root, target, runner)
    changed = sorted(
        name
        for name in set(old) | set(new)
        if name.startswith(("delivery_note/migrations/", "delivery_note/web/models/"))
        and old.get(name) != new.get(name)
    )
    if changed:
        raise BackupError(
            "发布涉及模型或数据库迁移变更，需另行制定方案：" + ", ".join(changed)
        )
