"""使用真实 Git 归档和文件读取验证源码清单及安装依赖。"""

from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import BinaryIO, Sequence
import unittest

from scripts.backup.runtime import BackupError, SubprocessRunner
from scripts.deployment_sources import RUNTIME_PROBE, verify_backend_source


class SourceRunner(SubprocessRunner):
    def __init__(self, runtime: Path) -> None:
        self.runtime = runtime

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        timeout_seconds: int = 300,
    ) -> str:
        if list(arguments[:2]) == ["docker", "exec"]:
            probe = RUNTIME_PROBE.replace(
                "Path('/app')", "Path(" + repr(str(self.runtime)) + ")"
            )
            return subprocess.check_output([sys.executable, "-c", probe], text=True)
        return super().run(
            arguments, stdin=stdin, stdout=stdout, timeout_seconds=timeout_seconds
        )


class DeploymentSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repository"
        self.runtime = Path(temporary.name) / "runtime"
        for root in (self.root, self.runtime):
            (root / "delivery_note").mkdir(parents=True)
            (root / "delivery_note" / "probe.py").write_bytes(b"value = 1\n")
            (root / "requirements.lock").write_bytes(
                ("pip==" + version("pip") + "\n").encode()
            )
        self.runner = SourceRunner(self.runtime)
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Deployment Test"),
            ("config", "user.email", "deployment@example.invalid"),
            ("config", "core.autocrlf", "false"),
            ("add", "."),
            ("commit", "-qm", "fixture"),
        ):
            self.runner.run(["git", "-C", str(self.root), *args])
        self.revision = self.runner.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"]
        ).strip()

    def check(self) -> dict[str, object]:
        return verify_backend_source(
            self.root, "container", self.revision, self.revision, self.runner
        )

    def test_real_archive_probe_and_locked_dependency_pass(self) -> None:
        report = self.check()
        self.assertTrue(report["source_matches_revision"])
        self.assertTrue(report["dependencies_match_lock"])
        self.assertEqual(report["source_files"], 2)

    def test_missing_source_extra_source_and_modified_lock_fail(self) -> None:
        original = self.runtime / "delivery_note" / "probe.py"
        original.unlink()
        with self.assertRaisesRegex(BackupError, "probe.py"):
            self.check()
        original.write_bytes(b"value = 1\n")
        extra = self.runtime / "delivery_note" / "extra.py"
        extra.write_bytes(b"extra = True\n")
        with self.assertRaisesRegex(BackupError, "extra.py"):
            self.check()
        extra.unlink()
        (self.runtime / "requirements.lock").write_bytes(b"pip==0\n")
        with self.assertRaisesRegex(BackupError, "requirements.lock"):
            self.check()

    def test_installed_dependency_must_match_identical_lock_files(self) -> None:
        for root in (self.root, self.runtime):
            (root / "requirements.lock").write_bytes(b"pip==0\n")
        self.runner.run(["git", "-C", str(self.root), "add", "."])
        self.runner.run(
            ["git", "-C", str(self.root), "commit", "-qm", "wrong dependency"]
        )
        self.revision = self.runner.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"]
        ).strip()
        with self.assertRaisesRegex(BackupError, "运行依赖.*pip"):
            self.check()

    def test_bytecode_cache_is_not_reported_as_source(self) -> None:
        cache = self.runtime / "delivery_note" / "__pycache__"
        cache.mkdir()
        (cache / "probe.pyc").write_bytes(b"cache")
        self.assertEqual(self.check()["source_files"], 2)

    def test_probe_does_not_expose_environment_credentials(self) -> None:
        report = json.loads(self.runner.run(["docker", "exec"]))
        self.assertEqual(set(report), {"files", "versions"})
