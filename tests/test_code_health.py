import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_code_health import (
    changed_files,
    check_import_cycles,
    check_new_python_types,
    check_sizes,
)
from scripts.python_imports import import_cycles


class CodeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "--quiet")
        self.git("config", "user.name", "Quality Check")
        self.git("config", "user.email", "quality@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.write("legacy.py", "value = 1\n" * 301)
        self.write("small.py", "value = 1\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "fixture")

    def git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=self.root, encoding="utf-8"
        ).strip()

    def write(self, name: str, content: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_new_file_and_previously_small_file_cannot_exceed_limit(self) -> None:
        self.write("新增 文件.ts", "// 合成代码\n" * 301)
        self.write("small.py", "value = 1\n" * 301)
        failures, warnings = check_sizes(self.root, changed_files(self.root), "HEAD")
        self.assertEqual(len(failures), 2)
        self.assertEqual(warnings, [])

    def test_legacy_long_file_is_reported_without_blocking(self) -> None:
        self.write("legacy.py", "value = 2\n" * 302)
        failures, warnings = check_sizes(self.root, changed_files(self.root), "HEAD")
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 1)

    def test_blank_lines_count_and_lockfiles_are_excluded(self) -> None:
        self.write("blank.py", "\n" * 301)
        self.write("frontend/package-lock.json", "\n" * 400)
        failures, _warnings = check_sizes(self.root, changed_files(self.root), "HEAD")
        self.assertEqual(len(failures), 1)
        self.assertIn("blank.py", failures[0])

    def test_deleted_files_do_not_fail(self) -> None:
        self.git("rm", "small.py")
        self.assertEqual(changed_files(self.root), [])

    def test_commit_range_includes_all_commits_but_not_untracked_files(self) -> None:
        base = self.git("rev-parse", "HEAD")
        for name in ("first.py", "second.py"):
            self.write(name, "value = 1\n")
            self.git("add", ".")
            self.git("commit", "--quiet", "-m", name)
        self.write("untracked.py", "value = 1\n")
        self.assertEqual(changed_files(self.root, base), ["first.py", "second.py"])

    def test_invalid_base_fails(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            changed_files(self.root, "missing-ref")

    def test_new_python_type_error_is_rejected(self) -> None:
        self.write("broken.py", 'def value() -> int:\n    return "错误类型"\n')
        self.assertNotEqual(
            check_new_python_types(self.root, changed_files(self.root), "HEAD"), 0
        )

    def test_valid_new_python_module_passes_types(self) -> None:
        self.write("valid.py", "def value() -> int:\n    return 1\n")
        self.assertEqual(
            check_new_python_types(self.root, changed_files(self.root), "HEAD"), 0
        )

    def test_relative_import_cycle_is_detected(self) -> None:
        self.write("delivery_note/__init__.py", "")
        self.write("delivery_note/first.py", "from . import second\n")
        self.write("delivery_note/second.py", "from .first import value\n")
        cycles = import_cycles(self.root / "delivery_note")
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0][0], cycles[0][-1])

    def test_script_import_cycle_is_included_in_project_gate(self) -> None:
        self.write("scripts/__init__.py", "")
        self.write("scripts/first.py", "from . import second\n")
        self.write("scripts/second.py", "from . import first\n")
        cycles = check_import_cycles(self.root)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]), {"scripts.first", "scripts.second"})

    def test_type_only_import_does_not_create_runtime_cycle(self) -> None:
        self.write("delivery_note/__init__.py", "")
        self.write("delivery_note/first.py", "from . import second\n")
        self.write(
            "delivery_note/second.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n    from . import first\n",
        )
        self.assertEqual(import_cycles(self.root / "delivery_note"), [])

    def test_type_checking_else_branch_is_a_runtime_dependency(self) -> None:
        self.write("delivery_note/__init__.py", "")
        self.write("delivery_note/first.py", "from . import second\n")
        self.write(
            "delivery_note/second.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n    pass\nelse:\n    from . import first\n",
        )
        self.assertEqual(len(import_cycles(self.root / "delivery_note")), 1)


if __name__ == "__main__":
    unittest.main()
