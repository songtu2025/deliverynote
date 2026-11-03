"""登记已审核的结构变更，限定发布时允许的模型和迁移差异。"""

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryFile

from scripts.backup.runtime import BackupError, Runner, compose
from scripts.deployment_sources import source_files
from scripts.release_common import ReleaseConfig


MODEL_FILE = "delivery_note/web/models/batches.py"
MODEL_EXPORTS_FILE = "delivery_note/web/models/__init__.py"
RUNNER_FILE = "delivery_note/migrations/runner.py"


@dataclass(frozen=True)
class SchemaChange:
    """按模型文件登记变更；字段使用“类名.字段名”限定归一化范围。"""

    migration: str
    migration_function: str
    fields: frozenset[str]
    requires_full_release: bool
    model_file: str = MODEL_FILE
    model_imports: frozenset[tuple[str, str]] = frozenset()
    models: frozenset[str] = frozenset()

    @property
    def files(self) -> frozenset[str]:
        return frozenset(
            {
                self.model_file,
                RUNNER_FILE,
                f"delivery_note/migrations/{self.migration}.py",
                *({MODEL_EXPORTS_FILE} if self.models else set()),
            }
        )


REVIEWED_SCHEMA_CHANGES = {
    "exception-transfers": SchemaChange(
        migration="exception_transfers",
        migration_function="migrate_exception_transfers",
        fields=frozenset({"ExceptionRecord.transfers"}),
        requires_full_release=False,
        model_imports=frozenset({("sqlalchemy.orm", "relationship")}),
        models=frozenset({"ExceptionTransfer"}),
    ),
    "inbound-receipts": SchemaChange(
        migration="inbound_receipts",
        migration_function="migrate_inbound_receipts",
        fields=frozenset(
            {
                "SelfOperatedBatch.receipt_snapshot",
                "BatchFile.receipt_context",
                "BatchFile.receipt_sites",
            }
        ),
        requires_full_release=True,
        model_imports=frozenset({("typing", "Any")}),
    ),
    "document-note-text": SchemaChange(
        migration="batch_file_document_note_text",
        migration_function="migrate_batch_file_document_note_text",
        fields=frozenset({"BatchFile.document_note"}),
        requires_full_release=False,
        model_imports=frozenset({("sqlalchemy", "Text")}),
    ),
}


def reviewed_changes(names: tuple[str, ...]) -> tuple[SchemaChange, ...]:
    """配置和结构校验共用名称检查，避免绕过命令行选项限制。"""
    changes = []
    seen = set()
    for name in names:
        if name not in REVIEWED_SCHEMA_CHANGES:
            raise BackupError(f"未登记的结构变更：{name}")
        if name in seen:
            raise BackupError(f"重复声明结构变更：{name}")
        seen.add(name)
        changes.append(REVIEWED_SCHEMA_CHANGES[name])
    return tuple(changes)


def _normalize_model(tree: ast.Module, changes: tuple[SchemaChange, ...]) -> None:
    fields = {field for change in changes for field in change.fields}
    models = {model for change in changes for model in change.models}
    imports = {entry for change in changes for entry in change.model_imports}
    model_modules = {
        Path(change.model_file).stem for change in changes if change.models
    }
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            node.body = [
                statement
                for statement in node.body
                if not (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and f"{node.name}.{statement.target.id}" in fields
                )
            ]
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            node.names = [
                alias
                for alias in node.names
                if (node.module, alias.name) not in imports or alias.asname is not None
            ]
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 1
            and node.module in model_modules
        ):
            node.names = [
                alias
                for alias in node.names
                if alias.name not in models or alias.asname is not None
            ]
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            node.value.elts = [
                entry
                for entry in node.value.elts
                if not (isinstance(entry, ast.Constant) and entry.value in models)
            ]
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and not node.names)
        and not (isinstance(node, ast.ClassDef) and node.name in models)
    ]


def _normalize_runner(tree: ast.Module, changes: tuple[SchemaChange, ...]) -> None:
    imports = {(change.migration, change.migration_function) for change in changes}
    functions = {change.migration_function for change in changes}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            node.names = [
                alias
                for alias in node.names
                if not (
                    alias.name == "migrate" and (node.module, alias.asname) in imports
                )
            ]
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "MIGRATIONS"
            and isinstance(node.value, ast.Tuple)
        ):
            node.value.elts = [
                entry
                for entry in node.value.elts
                if not (isinstance(entry, ast.Name) and entry.id in functions)
            ]
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and not node.names)
    ]


def _normalized_source(
    root: Path,
    revision: str,
    name: str,
    changes: tuple[SchemaChange, ...],
    runner: Runner,
) -> str:
    source = runner.run(["git", "-C", str(root), "show", f"{revision}:{name}"])
    tree = ast.parse(source)
    if name == RUNNER_FILE:
        _normalize_runner(tree, changes)
    else:
        _normalize_model(
            tree,
            tuple(
                change
                for change in changes
                if change.model_file == name
                or (name == MODEL_EXPORTS_FILE and change.models)
            ),
        )
    return ast.dump(tree)


def verify_reviewed_schema(
    root: Path, revision: str, target: str, names: tuple[str, ...], runner: Runner
) -> None:
    changes = reviewed_changes(names)
    expected = {name for change in changes for name in change.files}
    old, _ = source_files(root, revision, runner)
    new, _ = source_files(root, target, runner)
    changed = {
        name
        for name in set(old) | set(new)
        if name.startswith(("delivery_note/migrations/", "delivery_note/web/models/"))
        and old.get(name) != new.get(name)
    }
    if not changed:
        return
    if changed != expected:
        raise BackupError(
            "结构变更文件与声明不一致；未声明文件："
            + ", ".join(sorted(changed - expected))
            + "；缺少变更文件："
            + ", ".join(sorted(expected - changed))
        )
    checked = {RUNNER_FILE, *(change.model_file for change in changes)}
    if any(change.models for change in changes):
        checked.add(MODEL_EXPORTS_FILE)
    for name in sorted(checked):
        if _normalized_source(
            root, revision, name, changes, runner
        ) != _normalized_source(root, target, name, changes, runner):
            raise BackupError(f"已审核结构变更之外存在变化：{name}")


def run_schema_migrations(config: ReleaseConfig, runner: Runner) -> None:
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
