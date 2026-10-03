from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.backup.runtime import BackupError
from scripts.backup_deliverynote import build_parser, main
from tests.support.backup import BackupTestCase, FakeRunner


class BackupCliTests(BackupTestCase):
    def arguments(self) -> list[str]:
        return [
            "--compose-file",
            str(self.compose_file),
            "--env-file",
            str(self.env_file),
            "--destination",
            str(self.destination),
            "--check-only",
        ]

    def test_check_only_outputs_ready_json_without_maintenance_or_backup(self) -> None:
        output = io.StringIO()
        runner = FakeRunner()
        with patch("scripts.backup_deliverynote.SubprocessRunner", return_value=runner):
            with redirect_stdout(output):
                code = main(self.arguments())
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["active_jobs"], 0)
        self.assertFalse(any("stop" in command for command in runner.commands))
        self.assertFalse(self.destination.exists())

    def test_controlled_failure_outputs_stderr_and_exit_code_one(self) -> None:
        output = io.StringIO()
        with patch(
            "scripts.backup_deliverynote.inspect_environment",
            side_effect=BackupError("环境检查失败"),
        ):
            with redirect_stderr(output):
                code = main(self.arguments())
        self.assertEqual(code, 1)
        self.assertIn("备份失败：环境检查失败", output.getvalue())

    def test_original_cli_defaults_are_preserved(self) -> None:
        arguments = build_parser().parse_args(["--destination", str(self.destination)])
        expected = {
            "compose_file": Path("compose.yaml"),
            "env_file": Path(".env"),
            "project_name": "deliverynote",
            "lock_file": Path("/run/lock/deliverynote-backup.lock"),
            "stop_timeout_seconds": 60,
            "job_drain_timeout_seconds": 1800,
            "job_poll_seconds": 5,
            "service_wait_timeout_seconds": 120,
            "snapshot_timeout_seconds": 3600,
            "retention_count": 0,
            "check_only": False,
        }
        for name, value in expected.items():
            with self.subTest(argument=name):
                self.assertEqual(getattr(arguments, name), value)

    def test_script_and_module_entry_points_both_expose_original_flags(self) -> None:
        project = Path(__file__).resolve().parents[2]
        launchers = [
            ([str(project / "scripts/backup_deliverynote.py")], self.root),
            (["-m", "scripts.backup_deliverynote"], project),
        ]
        for arguments, directory in launchers:
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [sys.executable, *arguments, "--help"],
                    cwd=directory,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertIn("--check-only", completed.stdout)
                self.assertIn("--retention-count", completed.stdout)
