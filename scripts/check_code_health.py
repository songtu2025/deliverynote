"""按 Git 变更检查代码规模，并检查核心包的导入循环。"""

import argparse
from pathlib import Path
import subprocess
import sys

from scripts.python_imports import import_cycles

CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
}
MAX_FILE_LINES = 300
COMPLEXITY_RULES = "C901,PLR0911,PLR0912,PLR0913,PLR0915"


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, encoding="utf-8", stderr=subprocess.PIPE
    )


def changed_files(root: Path, base: str | None = None) -> list[str]:
    reference = _git(
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{base or 'HEAD'}^{{commit}}",
    ).strip()
    names = _git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        reference,
        *(["HEAD"] if base else []),
    ).split("\0")
    if base is None:
        names.extend(
            _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        )
    return sorted(
        name
        for name in set(names)
        if Path(name).suffix in CODE_EXTENSIONS
        and not name.endswith("package-lock.json")
        and (root / name).is_file()
    )


def check_sizes(root: Path, files: list[str], base: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    for name in files:
        lines = len((root / name).read_text(encoding="utf-8-sig").splitlines())
        if lines <= MAX_FILE_LINES:
            continue
        try:
            old_lines = len(_git(root, "show", f"{base}:{name}").splitlines())
        except subprocess.CalledProcessError:
            old_lines = 0
        message = f"{name}: {lines} 行（基线 {old_lines} 行）"
        if old_lines > MAX_FILE_LINES:
            warnings.append(f"存量规模提醒：{message}")
        else:
            failures.append(f"超过新增文件上限：{message}")
    return failures, warnings


def check_new_python_complexity(root: Path, files: list[str], base: str) -> int:
    new_python: list[str] = []
    tracked = set(_git(root, "ls-tree", "-r", "--name-only", "-z", base).split("\0"))
    for name in files:
        if name.endswith(".py") and name not in tracked:
            new_python.append(name)
    if not new_python:
        return 0
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            COMPLEXITY_RULES,
            *new_python,
        ],
        cwd=root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="CI 变更范围的起始提交")
    args = parser.parse_args()
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    files = changed_files(root, args.base)
    base = args.base or "HEAD"
    failures, warnings = check_sizes(root, files, base)
    cycles = import_cycles(root / "delivery_note")
    for message in [*warnings, *failures]:
        print(message)
    for cycle in cycles:
        print(f"Python 导入循环：{' -> '.join(cycle)}")
    complexity_status = check_new_python_complexity(root, files, base)
    print(f"规模检查：{len(files)} 个变更文件，{len(failures)} 个失败")
    print(f"Python 静态导入检查：{len(cycles)} 个循环")
    return int(bool(failures or cycles or complexity_status))


if __name__ == "__main__":
    raise SystemExit(main())
