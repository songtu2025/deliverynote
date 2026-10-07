"""在独立真实环境中验证恢复拒绝、资源门禁和只读命令。"""

import json
import os
import subprocess
import sys
from unittest.mock import patch
import unittest

from scripts.backup.manifest import read_manifest, verify_image
from scripts.backup.resources import extract_resource_archive
from scripts.backup.runtime import BackupError, SubprocessRunner
from tests.support.business_case import RecoveryCase


@unittest.skipUnless(
    os.environ.get("RECOVERY_BUSINESS_DOCKER_TESTS") == "1",
    "需显式启用隔离 Docker 恢复门禁演练",
)
class RecoveryValidationDockerTests(RecoveryCase):
    def create_baseline(self) -> None:
        super().create_baseline()
        self.scenario.split_and_export()

    def assert_target_stopped(self) -> None:
        self.assertEqual(self.target.url, "")
        self.assertEqual(
            self.target.compose("ps", "--status", "running", "--services"), "db"
        )

    def test_readonly_cli_checks_real_backup_and_rejects_missing_image(self) -> None:
        directory, snapshot = self.backup_baseline()
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        for entry in (["scripts/check_restore.py"], ["-m", "scripts.check_restore"]):
            process = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    *entry,
                    "--backup-directory",
                    str(directory),
                    "--image",
                    self.fixture.api_image,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)["status"], "passed")
            self.assertFalse(json.loads(process.stdout)["restore_performed"])
        process = subprocess.run(
            [
                sys.executable,
                "-S",
                "-m",
                "scripts.check_restore",
                "--backup-directory",
                str(directory),
                "--image",
                "sha256:" + "0" * 64,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})
        self.assert_source_unchanged(snapshot)

    def test_manifest_mismatches_are_rejected_before_target_writes(self) -> None:
        self.target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        path = directory / "BACKUP-METADATA.json"
        original = path.read_bytes()
        changes = (
            ("schema_version", 2),
            ("application_image", {"id": "sha256:" + "0" * 64}),
            ("resources", {"status": "failed", "source": {}, "restored": {}}),
        )
        with (
            patch("tests.support.business_restore._restore_database") as restore,
            patch("tests.support.business_restore.extract_resource_archive") as extract,
        ):
            for key, value in changes:
                with self.subTest(key=key):
                    metadata = json.loads(original)
                    metadata[key] = value
                    path.write_text(json.dumps(metadata), encoding="utf-8")
                    with self.assertRaises(BackupError):
                        self.target.restore_from(self.fixture, directory)
            restore.assert_not_called()
            extract.assert_not_called()
        path.write_bytes(original)
        self.assertEqual(
            self.target.database_query(
                "SELECT datname FROM pg_database WHERE datname='delivery_note'",
                "postgres",
            ),
            "",
        )
        self.assert_target_stopped()
        self.assert_source_unchanged(snapshot)

    def test_nonempty_target_database_and_volume_are_not_overwritten(self) -> None:
        self.target = self.empty_target()
        directory, snapshot = self.backup_baseline()
        with patch("tests.support.business_restore._restore_database") as restore:
            self.target.compose(
                "exec", "-T", "db", "createdb", "-U", "delivery_note", "delivery_note"
            )
            with self.assertRaisesRegex(BackupError, "数据库必须为空"):
                self.target.restore_from(self.fixture, directory)
            self.target.compose(
                "exec", "-T", "db", "dropdb", "-U", "delivery_note", "delivery_note"
            )
            self.target.run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--volume",
                self.target.volume + ":/data",
                self.target.api_image,
                "python",
                "-c",
                "from pathlib import Path; "
                "Path('/data/keep.bin').write_bytes(b'keep-original')",
            )
            with self.assertRaisesRegex(BackupError, "文件卷必须为空"):
                self.target.restore_from(self.fixture, directory)
            restore.assert_not_called()
        contents = self.target.run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--volume",
            self.target.volume + ":/data:ro",
            self.target.api_image,
            "python",
            "-c",
            "from pathlib import Path; print(Path('/data/keep.bin').read_text())",
        )
        self.assertEqual(contents, "keep-original")
        self.assert_target_stopped()
        self.assert_source_unchanged(snapshot)

    def test_actual_resource_mismatch_blocks_service_start(self) -> None:
        self.target = self.empty_target()
        directory, snapshot = self.backup_baseline()

        def changed_extract(*arguments: object) -> None:
            extract_resource_archive(
                self.target.config,
                SubprocessRunner(),
                self.target.api_image,
                directory / "delivery_data.tar.gz",
                self.target.volume,
            )
            self.target.run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--volume",
                self.target.volume + ":/data",
                self.target.api_image,
                "python",
                "-c",
                "from delivery_note.gerpgo import GerpgoSettings,save_gerpgo_settings; "
                "save_gerpgo_settings('/data/storage',GerpgoSettings('https://example.test/api',"
                "'restore-test','restore-test-key','managed'))",
            )

        with (
            patch(
                "tests.support.business_restore.extract_resource_archive",
                side_effect=changed_extract,
            ),
            patch.object(self.target, "start_services") as start,
        ):
            with self.assertRaisesRegex(BackupError, "运行资源与备份证据不一致"):
                self.target.restore_from(self.fixture, directory)
            start.assert_not_called()
        self.assert_target_stopped()
        self.assert_source_unchanged(snapshot)

    def test_same_image_with_another_tag_is_accepted_without_revision_evidence(
        self,
    ) -> None:
        directory, snapshot = self.backup_baseline()
        path = directory / "BACKUP-METADATA.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["application_image"]["revision"] = None
        path.write_text(json.dumps(metadata), encoding="utf-8")
        manifest = read_manifest(directory)
        alias = self.fixture.project + ":restore-alias"
        self.fixture.images.append(alias)
        self.fixture.run("docker", "tag", manifest.image_id, alias)
        self.assertEqual(
            verify_image(manifest, SubprocessRunner(), alias), manifest.image_id
        )
        self.assert_source_unchanged(snapshot)
