"""只读预检命令不依赖业务库，失败返回非零且不输出凭据。"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from scripts.check_restore import main
from scripts.backup.runtime import BackupError
from tests.support.restore_manifest import ManifestTestCase


class RestoreCliTests(ManifestTestCase):
    def test_cli_checks_backup_and_image_without_restoring(self) -> None:
        output = io.StringIO()
        with (
            patch(
                "scripts.check_restore.verify_image", return_value="sha256:" + "a" * 64
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(
                main(
                    [
                        "--backup-directory",
                        str(self.directory),
                        "--image",
                        "test:latest",
                    ]
                ),
                0,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["scope"], "backup_and_image")
        self.assertFalse(result["restore_performed"])

    def test_cli_missing_image_and_corrupt_metadata_return_nonzero(self) -> None:
        with (
            patch(
                "scripts.check_restore.verify_image",
                side_effect=BackupError("镜像不存在"),
            ),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(["--backup-directory", str(self.directory), "--image", "missing"]),
                1,
            )
        self.path.write_text("[]", encoding="utf-8")
        with (
            patch("scripts.check_restore.verify_image") as verify,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(
                main(["--backup-directory", str(self.directory), "--image", "test"]), 1
            )
        verify.assert_not_called()

    def test_direct_and_module_help_need_only_standard_library(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for arguments in (
            ["scripts/check_restore.py"],
            ["-m", "scripts.check_restore"],
        ):
            process = subprocess.run(
                [sys.executable, "-S", *arguments, "--help"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("--backup-directory", process.stdout)
