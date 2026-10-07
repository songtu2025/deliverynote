"""验证运行资源识别、异常保留及审计无写入。"""

import json
from pathlib import Path
import shutil
import tarfile
from unittest.mock import patch

from sqlalchemy import select

from delivery_note.gerpgo import GerpgoSettings, save_gerpgo_settings
from delivery_note.purchase_detail_cache import (
    build_purchase_detail_cache,
    purchase_cache_source_identity,
    purchase_detail_cache_path,
    write_purchase_detail_cache,
)
from delivery_note.web.input_versions import BUILTIN_TEMPLATES, BuiltinTemplate
from delivery_note.web.models import InputVersion
from scripts.audit_storage import AuditEntry, audit_storage
from scripts.backup.archive import validate_data_archive
from scripts.quarantine_files import inventory
from scripts.storage_quarantine import prepare_quarantine
from tests.support.storage_audit import StorageAuditCase


class StorageResourceTests(StorageAuditCase):
    def seed_runtime(self) -> tuple[Path, Path]:
        settings = GerpgoSettings(
            "https://example.test/api", "测试应用", "不可输出的测试密钥", "managed"
        )
        save_gerpgo_settings(self.storage, settings)
        cache = purchase_detail_cache_path(self.storage)
        payload = build_purchase_detail_cache(
            purchase_cache_source_identity(settings.base_url, settings.app_id),
            [({"code": "PO-1"}, {"poCode": "PO-1", "quantity": 12})],
        )
        write_purchase_detail_cache(cache, payload)
        return self.storage / "config/gerpgo.json", cache

    def entry(self, relative: str) -> AuditEntry:
        return next(
            entry
            for entry in audit_storage(self.url, self.storage)["entries"]
            if entry["path"] == relative
        )

    def register_builtin(self, path: Path) -> BuiltinTemplate:
        template = next(t for t in BUILTIN_TEMPLATES if t.kind == "inbound_template")
        shutil.copyfile(template.path, path)
        with self.app.state.database.session() as session:
            version = session.scalar(
                select(InputVersion).where(InputVersion.kind == template.kind)
            )
            version.storage_path = str(path)
            session.commit()
        return BuiltinTemplate(
            template.kind, template.name, template.original_name, path
        )

    def test_runtime_resources_are_identified_without_writes_or_credentials(self):
        self.seed_runtime()
        before = self.snapshot_files()
        report = audit_storage(self.url, self.storage)
        self.assertEqual(report["counts"]["managed_runtime"], 2)
        for relative in ("config/gerpgo.json", "cache/purchase-details-v1.json"):
            entry = self.entry(relative)
            self.assertEqual(entry["category"], "managed_runtime")
            self.assertEqual(entry["validation"], "passed")
            self.assertEqual(entry["recovery_source"], "data_volume")
        self.assertEqual(
            self.entry("cache/purchase-details-v1.json")["valid_entries"], 1
        )
        self.assertNotIn("不可输出的测试密钥", json.dumps(report, ensure_ascii=False))
        self.assertNotIn("https://example.test/api", json.dumps(report))
        self.assertEqual(audit_storage(self.url, self.storage), report)
        self.assertEqual(self.snapshot_files(), before)

    def test_invalid_config_is_not_hidden_by_valid_environment(self):
        config, _ = self.seed_runtime()
        config.write_text("[]", encoding="utf-8")
        with patch.dict(
            "os.environ",
            {"GERPGO_APP_ID": "环境应用", "GERPGO_APP_KEY": "环境密钥"},
        ):
            self.assertEqual(self.entry("config/gerpgo.json")["category"], "unknown")
            self.assertEqual(
                self.entry("cache/purchase-details-v1.json")["validation"], "failed"
            )

    def test_cache_corruption_source_change_and_invalid_schema_remain_unknown(self):
        _, cache = self.seed_runtime()
        original = json.loads(cache.read_text(encoding="utf-8"))
        for change in ("detail", "source_identity", "schema_version", "orders"):
            with self.subTest(change=change):
                payload = json.loads(json.dumps(original))
                if change == "detail":
                    payload["orders"]["PO-1"]["detail"]["quantity"] = 13
                elif change == "orders":
                    payload[change] = []
                else:
                    payload[change] = "无效"
                write_purchase_detail_cache(cache, payload)
                entry = self.entry("cache/purchase-details-v1.json")
                self.assertEqual(entry["category"], "unknown")
                self.assertEqual(entry["validation"], "failed")

    def test_empty_valid_cache_is_a_managed_resource(self):
        _, cache = self.seed_runtime()
        payload = json.loads(cache.read_text(encoding="utf-8"))
        payload["orders"] = {}
        write_purchase_detail_cache(cache, payload)
        self.assertEqual(
            self.entry("cache/purchase-details-v1.json")["category"], "managed_runtime"
        )

    def test_directory_at_runtime_filename_is_reported(self):
        config, _ = self.seed_runtime()
        config.unlink()
        config.mkdir()
        self.assertEqual(self.entry("config/gerpgo.json")["kind"], "directory")
        self.assertEqual(self.entry("config/gerpgo.json")["category"], "unknown")

    def test_builtin_template_is_validated_and_missing_reference_is_reported(self):
        path = self.root / "builtin.xlsx"
        template = self.register_builtin(path)
        with patch("scripts.storage_resources.BUILTIN_TEMPLATES", (template,)):
            entry = self.entry(path.as_posix())
            self.assertEqual(entry["category"], "builtin_resource")
            self.assertEqual(entry["recovery_source"], "application_image")
            self.assertEqual(len(entry["sha256"]), 64)
            path.write_bytes(b"broken")
            self.assertEqual(self.entry(path.as_posix())["category"], "unknown")
            path.unlink()
            self.assertEqual(
                self.entry(path.as_posix())["category"], "missing_reference"
            )

    def test_wrong_template_kind_and_other_external_paths_remain_unknown(self):
        path = self.root / "builtin.xlsx"
        template = self.register_builtin(path)
        with self.app.state.database.session() as session:
            version = session.scalar(
                select(InputVersion).where(InputVersion.kind == template.kind)
            )
            version.kind = "陌生类型"
            session.commit()
        with patch("scripts.storage_resources.BUILTIN_TEMPLATES", (template,)):
            self.assertEqual(self.entry(path.as_posix())["category"], "unknown")

    def test_runtime_symlink_is_not_read(self):
        config, _ = self.seed_runtime()
        outside = self.root / "secret.json"
        outside.write_text("{}", encoding="utf-8")
        config.unlink()
        try:
            config.symlink_to(outside)
        except OSError:
            self.skipTest("当前账号没有符号链接权限")
        with patch("scripts.storage_resources.load_gerpgo_settings") as loader:
            self.assertEqual(self.entry("config/gerpgo.json")["kind"], "symlink")
            self.assertEqual(
                self.entry("cache/purchase-details-v1.json")["category"], "unknown"
            )
            loader.assert_not_called()

    def test_managed_resources_and_builtin_cannot_be_quarantined(self):
        self.seed_runtime()
        path = self.root / "builtin.xlsx"
        template = self.register_builtin(path)
        before = self.snapshot_files()
        with patch("scripts.storage_resources.BUILTIN_TEMPLATES", (template,)):
            for relative in (
                "config/gerpgo.json",
                "cache/purchase-details-v1.json",
                str(path),
            ):
                with self.subTest(path=relative), self.assertRaises(ValueError):
                    prepare_quarantine(
                        self.url, self.storage, [relative], self.root / "quarantine/run"
                    )
        self.assertEqual(self.snapshot_files(), before)
        self.assertFalse((self.root / "quarantine/run").exists())

    def test_builtin_symlink_is_not_validated(self):
        path = self.root / "builtin.xlsx"
        template = self.register_builtin(path)
        outside = self.root / "outside.xlsx"
        path.rename(outside)
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("当前账号没有符号链接权限")
        with (
            patch("scripts.storage_resources.BUILTIN_TEMPLATES", (template,)),
            patch(
                "scripts.storage_resources.validate_self_operated_template_workbook"
            ) as validator,
        ):
            entry = self.entry(path.as_posix())
            self.assertEqual(entry["category"], "unknown")
            self.assertEqual(entry["kind"], "symlink")
            validator.assert_not_called()

    def test_restored_runtime_files_keep_hash_permissions_and_validation(self):
        config, cache = self.seed_runtime()
        before = {
            path.relative_to(self.storage): inventory(path)["."]
            for path in (config, cache)
        }
        archive_path = self.root / "data.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(self.storage, arcname="storage")
        validate_data_archive(archive_path)
        restored = self.root / "restored"
        restored.mkdir()
        with tarfile.open(archive_path, "r:gz") as archive:
            # 仅解包本测试生成并通过路径校验的隔离归档。
            archive.extractall(restored)
        for relative, state in before.items():
            actual = inventory(restored / "storage" / relative)["."]
            self.assertEqual(actual["sha256"], state["sha256"])
            self.assertEqual(actual["mode"], state["mode"])
        report = audit_storage(self.url, restored / "storage")
        self.assertEqual(report["counts"]["managed_runtime"], 2)
        self.assertEqual(
            next(
                entry
                for entry in report["entries"]
                if entry.get("purpose") == "采购详情缓存"
            )["valid_entries"],
            1,
        )
