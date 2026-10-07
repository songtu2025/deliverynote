"""恢复预检必须拒绝缺失证据和不一致的备份，不修改备份。"""

import json
from typing import Any
from unittest.mock import patch

from scripts.backup.manifest import read_manifest, verify_image
from scripts.backup.runtime import BackupError
from tests.support.backup import FakeRunner
from tests.support.restore_manifest import ManifestTestCase


class BackupManifestTests(ManifestTestCase):
    def test_valid_backup_is_readonly_and_revision_is_optional(self) -> None:
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        manifest = read_manifest(self.directory)
        self.assertEqual(manifest.image_id, "sha256:" + "a" * 64)
        self.assertEqual(manifest.storage_root, "/data/storage")
        self.assertEqual(
            manifest.counts, self.metadata["database"]["source_row_counts"]
        )
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.directory.iterdir()}
        )

    def test_schema_and_completion_evidence_are_required(self) -> None:
        original = self.path.read_bytes()
        cases: tuple[tuple[str, Any], ...] = (
            ("schema_version", 2),
            ("schema_version", 4),
            ("status", "incomplete"),
            ("resources", {}),
            ("application_image", {"id": "deliverynote:latest"}),
            ("database", {}),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.metadata = json.loads(original)
                self.metadata[key] = value
                self.save()
                with self.assertRaises(BackupError):
                    read_manifest(self.directory)
        self.path.write_bytes(original)
        (self.directory / "READY").unlink()
        with self.assertRaisesRegex(BackupError, "完成标记"):
            read_manifest(self.directory)

    def test_resource_and_database_restore_results_must_match(self) -> None:
        self.metadata["resources"]["restored"]["/data/storage/config/gerpgo.json"] = {}
        self.save()
        with self.assertRaisesRegex(BackupError, "资源恢复证据"):
            read_manifest(self.directory)
        self.metadata["resources"]["restored"] = self.metadata["resources"]["source"]
        self.metadata["database"]["restore_verification"]["restored_row_counts"][
            "users"
        ] += 1
        self.save()
        with self.assertRaisesRegex(BackupError, "数据库恢复证据"):
            read_manifest(self.directory)

    def test_equal_but_empty_resource_reports_are_rejected(self) -> None:
        self.metadata["resources"].update(source={}, restored={})
        self.save()
        with self.assertRaisesRegex(BackupError, "资源恢复证据"):
            read_manifest(self.directory)

    def test_malformed_metadata_is_rejected_without_echoing_contents(self) -> None:
        self.path.write_text('{"secret":"不能输出的密钥",', encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "元数据格式") as caught:
            read_manifest(self.directory)
        self.assertNotIn("不能输出的密钥", str(caught.exception))

    def test_file_corruption_and_checksum_list_are_rejected(self) -> None:
        dump = self.directory / "database.dump"
        original = dump.read_bytes()
        dump.write_bytes(original[:-1] + b"!")
        with self.assertRaisesRegex(BackupError, "校验和或大小不一致"):
            read_manifest(self.directory)
        dump.write_bytes(original)
        (self.directory / "SHA256SUMS").write_text("wrong", encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "校验和清单"):
            read_manifest(self.directory)

    def test_archive_counts_must_match_metadata(self) -> None:
        self.metadata["data_archive"]["files"] += 1
        self.save()
        with self.assertRaisesRegex(BackupError, "归档条目"):
            read_manifest(self.directory)

    def test_image_inspection_resolves_tag_and_never_pulls(self) -> None:
        runner = FakeRunner()
        manifest = read_manifest(self.directory)
        with patch.object(runner, "run", return_value=manifest.image_id) as run:
            self.assertEqual(
                verify_image(manifest, runner, "test:latest"), manifest.image_id
            )
        run.assert_called_once_with(
            ["docker", "image", "inspect", "--format", "{{.Id}}", "test:latest"]
        )
        with patch.object(runner, "run", return_value="sha256:" + "b" * 64):
            with self.assertRaisesRegex(BackupError, "镜像身份不匹配"):
                verify_image(manifest, runner, "test:latest")
