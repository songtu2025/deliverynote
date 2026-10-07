"""资源必须真实可读且与快照一致，失败时不得完成备份。"""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from typing import BinaryIO, Sequence
from unittest.mock import patch

from delivery_note.gerpgo import GerpgoSettings, save_gerpgo_settings
from delivery_note.purchase_detail_cache import (
    build_purchase_detail_cache,
    purchase_cache_source_identity,
    purchase_detail_cache_path,
    write_purchase_detail_cache,
)
from delivery_note.web.input_versions import BUILTIN_TEMPLATES, BuiltinTemplate
from scripts.backup.resource_probe import inspect_resources
from scripts.backup.runtime import BackupError
from scripts.backup.workflow import create_backup
from tests.support.backup import BackupTestCase, FakeRunner


class ResourceProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "storage"
        self.root.mkdir()
        self.settings = GerpgoSettings(
            "https://example.test/api", "测试应用", "不能输出的密钥", "managed"
        )
        self.config = self.root / "config/gerpgo.json"
        self.cache = purchase_detail_cache_path(self.root)

    def seed(self) -> None:
        save_gerpgo_settings(self.root, self.settings)
        payload = build_purchase_detail_cache(
            purchase_cache_source_identity(
                self.settings.base_url, self.settings.app_id
            ),
            [({"code": "PO-1"}, {"poCode": "PO-1", "quantity": 12})],
        )
        write_purchase_detail_cache(self.cache, payload)

    def test_valid_resources_preserve_hash_mode_owner_without_credentials(self) -> None:
        self.seed()
        before = {path: path.read_bytes() for path in (self.config, self.cache)}
        report = inspect_resources(self.root, [])
        for path in before:
            entry = report[str(path)]
            self.assertEqual(entry["validation"], "passed")
            self.assertEqual(entry["mode"], path.stat().st_mode & 0o777)
            self.assertEqual(entry["uid"], path.stat().st_uid)
            self.assertEqual(entry["gid"], path.stat().st_gid)
            self.assertEqual(len(str(entry["sha256"])), 64)
            self.assertEqual(path.read_bytes(), before[path])
        self.assertEqual(report[str(self.cache)]["valid_entries"], 1)
        self.assertNotIn(self.settings.app_key, json.dumps(report))

    def test_optional_resources_absent_are_explicit(self) -> None:
        report = inspect_resources(self.root, [])
        self.assertEqual(len(report), 2)
        self.assertTrue(all(item["validation"] == "absent" for item in report.values()))

    def test_cache_uses_environment_when_optional_config_is_absent(self) -> None:
        self.seed()
        self.config.unlink()
        with patch.dict(
            "os.environ",
            {
                "GERPGO_API_BASE_URL": self.settings.base_url,
                "GERPGO_APP_ID": self.settings.app_id,
                "GERPGO_APP_KEY": self.settings.app_key,
            },
        ):
            report = inspect_resources(self.root, [])
        self.assertEqual(report[str(self.config)]["validation"], "absent")
        self.assertEqual(report[str(self.cache)]["validation"], "passed")

    def test_corrupt_json_and_cache_source_are_rejected(self) -> None:
        self.seed()
        original = self.config.read_bytes()
        self.config.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "资源校验失败"):
            inspect_resources(self.root, [])
        self.config.write_bytes(original)
        payload = json.loads(self.cache.read_text(encoding="utf-8"))
        payload["source_identity"] = "wrong"
        write_purchase_detail_cache(self.cache, payload)
        with self.assertRaisesRegex(BackupError, "资源校验失败"):
            inspect_resources(self.root, [])

    def test_registered_builtin_is_validated_and_missing_or_wrong_kind_fails(
        self,
    ) -> None:
        original = BUILTIN_TEMPLATES[0]
        path = self.root.parent / "builtin.xlsx"
        shutil.copyfile(original.path, path)
        template = BuiltinTemplate(
            original.kind, original.name, original.original_name, path
        )
        with patch("scripts.storage_resources.BUILTIN_TEMPLATES", (template,)):
            report = inspect_resources(self.root, [(template.kind, str(path))])
            self.assertEqual(report[str(path)]["recovery_source"], "application_image")
            with self.assertRaisesRegex(BackupError, "外部引用"):
                inspect_resources(self.root, [("wrong", str(path))])
            with self.assertRaisesRegex(BackupError, "外部引用"):
                inspect_resources(
                    self.root, [(template.kind, str(path)), ("wrong", str(path))]
                )
            path.write_bytes(b"broken")
            with self.assertRaisesRegex(BackupError, "资源校验失败"):
                inspect_resources(self.root, [(template.kind, str(path))])
            path.unlink()
            with self.assertRaisesRegex(BackupError, "资源校验失败"):
                inspect_resources(self.root, [(template.kind, str(path))])

    def test_unknown_external_reference_is_not_certified(self) -> None:
        with self.assertRaisesRegex(BackupError, "外部引用"):
            inspect_resources(
                self.root, [("template", str(self.root.parent / "x.xlsx"))]
            )

    def test_runtime_symlink_is_rejected_before_loading(self) -> None:
        self.seed()
        outside = self.root.parent / "config.json"
        self.config.rename(outside)
        try:
            self.config.symlink_to(outside)
        except OSError:
            self.skipTest("当前账号没有符号链接权限")
        with patch("scripts.storage_resources.load_gerpgo_settings") as loader:
            with self.assertRaisesRegex(BackupError, "资源校验失败"):
                inspect_resources(self.root, [])
            loader.assert_not_called()


class BackupResourceGateTests(BackupTestCase):
    def test_ready_records_running_image_and_resource_verification(self) -> None:
        result = create_backup(
            self.config, runner=FakeRunner(), now=lambda: self.fixed_time
        )
        directory = Path(str(result["backup_directory"]))
        metadata = json.loads((directory / "BACKUP-METADATA.json").read_text())
        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["application_image"]["id"], "sha256:" + "a" * 64)
        self.assertEqual(metadata["resources"]["status"], "passed")
        self.assertTrue(result["resources_restore_verified"])

    def test_changed_restored_resource_cannot_mark_ready_and_cleans_up(self) -> None:
        runner = FakeRunner()
        runner.resource_changed = True
        self.assert_failed_backup(runner, "资源恢复结果与快照不一致")
        commands = runner.commands
        resume = next(i for i, c in enumerate(commands) if c[:2] == ("docker", "start"))
        extract = next(i for i, c in enumerate(commands) if "-xzf" in c)
        self.assertLess(resume, extract)
        self.assertTrue(any("dropdb" in c for c in commands))
        self.assertTrue(any(c[:3] == ("docker", "volume", "rm") for c in commands))

    def test_restore_volume_cleanup_failure_prevents_ready(self) -> None:
        runner = FakeRunner()
        runner.fail_resource_cleanup = True
        self.assert_failed_backup(runner, "恢复文件卷清理失败")
        self.assertTrue(any("dropdb" in c for c in runner.commands))

    def test_changed_reference_with_same_table_count_prevents_ready(self) -> None:
        runner = FakeRunner()
        original = runner._counts

        def counts(command: tuple[str, ...]) -> str:
            if (
                "json_agg" in command[-1]
                and command[command.index("-d") + 1] != "delivery_note"
            ):
                return '[["template", "/external/template.xlsx"]]'
            return original(command)

        with patch.object(runner, "_counts", side_effect=counts):
            self.assert_failed_backup(runner, "恢复库资源登记与快照不一致")
        self.assertTrue(any("dropdb" in c for c in runner.commands))

    def test_mutable_image_tag_is_rejected_before_maintenance(self) -> None:
        runner = FakeRunner()
        original = runner.run

        def run(
            arguments: Sequence[str],
            *,
            stdin: BinaryIO | None = None,
            stdout: BinaryIO | None = None,
            timeout_seconds: int = 300,
        ) -> str:
            if "{{.Image}}" in arguments:
                return "deliverynote:latest"
            return original(
                arguments, stdin=stdin, stdout=stdout, timeout_seconds=timeout_seconds
            )

        with patch.object(runner, "run", side_effect=run):
            with self.assertRaisesRegex(BackupError, "实际运行 API 镜像身份"):
                create_backup(self.config, runner=runner)
        self.assertFalse(any("stop" in c for c in runner.commands))
