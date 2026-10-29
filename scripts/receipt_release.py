"""累计实收发布只允许三项可空 JSON 字段的显式迁移。"""

import ast
import json
from pathlib import Path
from tempfile import TemporaryFile

from scripts.backup.runtime import BackupError, Runner, compose
from scripts.deployment_sources import source_files
from scripts.release_common import ReleaseConfig


SCHEMA_FILES = {
    "delivery_note/web/models/batches.py",
    "delivery_note/migrations/runner.py",
    "delivery_note/migrations/inbound_receipts.py",
}


def _normalized_source(root: Path, revision: str, name: str, runner: Runner) -> str:
    source = runner.run(["git", "-C", str(root), "show", f"{revision}:{name}"])
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            node.body = [
                statement
                for statement in node.body
                if not (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id
                    in {"receipt_snapshot", "receipt_context", "receipt_sites"}
                )
            ]
        if isinstance(node, ast.Tuple):
            node.elts = [
                entry
                for entry in node.elts
                if not (
                    isinstance(entry, ast.Name)
                    and entry.id == "migrate_inbound_receipts"
                )
            ]
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.ImportFrom)
            and (
                node.module == "inbound_receipts"
                or (
                    node.module == "typing"
                    and all(alias.name == "Any" for alias in node.names)
                )
            )
        )
    ]
    return ast.dump(tree)


def verify_receipt_migration(
    root: Path, revision: str, target: str, runner: Runner
) -> None:
    old, _ = source_files(root, revision, runner)
    new, _ = source_files(root, target, runner)
    changed = {
        name
        for name in set(old) | set(new)
        if name.startswith(("delivery_note/migrations/", "delivery_note/web/models/"))
        and old.get(name) != new.get(name)
    }
    if changed != SCHEMA_FILES:
        raise BackupError("累计实收迁移只允许已审核的三个模型/迁移文件")
    for name in sorted(SCHEMA_FILES - {"delivery_note/migrations/inbound_receipts.py"}):
        if _normalized_source(root, revision, name, runner) != _normalized_source(
            root, target, name, runner
        ):
            raise BackupError(f"累计实收迁移之外存在结构变化：{name}")


def migrate_receipts(config: ReleaseConfig, runner: Runner) -> None:
    """所有写入进程停止后，使用候选镜像显式执行统一迁移入口。"""
    document = runner.run(compose(config, "config", "--format", "json"))
    database_url = json.loads(document)["services"]["api"]["environment"][
        "DATABASE_URL"
    ]
    # 连接串留在子进程环境中，不进入日志或命令行参数。
    with TemporaryFile() as environment:
        environment.write(f"DATABASE_URL={database_url}\n".encode())
        environment.seek(0)
        runner.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                f"{config.project_name}_default",
                "--env-file",
                "/dev/stdin",
                config.image,
                "python",
                "-m",
                "delivery_note.migrations",
            ],
            stdin=environment,
        )
