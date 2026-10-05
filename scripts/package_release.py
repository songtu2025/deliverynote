"""用独立 Git 暂存区生成候选或指定提交源码包。"""

import argparse
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_code_health import CODE_EXTENSIONS, _git


SOURCE_ROOTS = {"delivery_note", "frontend", "scripts", "tests", ".github"}
SOURCE_EXTENSIONS = CODE_EXTENSIONS | {".svg", ".conf", ".txt", ".lock"}


def _new_source(name: str) -> bool:
    path = Path(name)
    return (
        path.parts[0] in SOURCE_ROOTS
        and not path.name.startswith(".env")
        and (
            path.suffix in SOURCE_EXTENSIONS
            or path.name in {"Dockerfile", ".dockerignore"}
        )
    )


def package_source(root: Path, output: Path, *, revision: str | None = None) -> str:
    if revision is not None:
        commit = _git(
            root, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
        ).strip()
        _git(
            root,
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "archive",
            "--format=tar.gz",
            "--output",
            str(output.resolve()),
            commit,
        )
        return commit
    tracked = _git(root, "ls-files", "-z").split("\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(
        "\0"
    )
    names = sorted(
        {name for name in tracked if name}
        | {name for name in untracked if name and _new_source(name)}
    )
    with TemporaryDirectory(prefix="deliverynote-candidate-index-") as directory:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        _git(root, "read-tree", "HEAD", env=environment)
        # Git 自身处理删除、换行转换、可执行位与符号链接，真实暂存区保持不变。
        _git(root, "--literal-pathspecs", "add", "--all", "--", *names, env=environment)
        tree = _git(root, "write-tree", env=environment).strip()
        _git(
            root,
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "archive",
            "--format=tar.gz",
            "--output",
            str(output.resolve()),
            tree,
        )
    return tree


def main() -> None:
    parser = argparse.ArgumentParser(description="生成可验证的候选或提交源码包。")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", help="省略时包含工作区源码修改和新增源码")
    arguments = parser.parse_args()
    tree = package_source(
        arguments.root.resolve(), arguments.output, revision=arguments.revision
    )
    print(f"源码包已生成：{arguments.output}；Git 对象：{tree}")


if __name__ == "__main__":
    main()
