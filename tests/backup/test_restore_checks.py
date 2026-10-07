"""空目标检查无写入，恢复后实际结果决定是否允许启动。"""

from unittest.mock import patch

from scripts.backup.manifest import BackupManifest
from scripts.backup.resources import ResourceContext, ResourceReport
from scripts.backup.restore_checks import check_empty_target, check_restored_target
from scripts.backup.runtime import BackupError
from tests.support.backup import BackupTestCase, FakeRunner


class RestoreTargetChecksTests(BackupTestCase):
    image = "sha256:" + "a" * 64

    def test_empty_target_checks_are_readonly(self) -> None:
        runner = FakeRunner()
        with patch.object(
            runner, "run", side_effect=["db\n", "", "test-volume", "empty"]
        ) as run:
            check_empty_target(self.config, runner, "test-volume", self.image)
        arguments = [call.args[0] for call in run.call_args_list]
        self.assertIn("readonly", arguments[-1][arguments[-1].index("--mount") + 1])
        self.assertIn("--read-only", arguments[-1])
        self.assertFalse(any("createdb" in c or "-xzf" in c for c in arguments))

    def test_running_services_database_and_volume_are_rejected_before_writes(
        self,
    ) -> None:
        cases = (
            (["db\napi"], "业务服务必须停止"),
            (["db", "delivery_note"], "数据库必须为空"),
            (["db", "", "test-volume", "nonempty"], "文件卷必须为空"),
            (["db", "", "other-volume"], "无法确认"),
        )
        for outputs, message in cases:
            with self.subTest(message=message):
                runner = FakeRunner()
                with patch.object(runner, "run", side_effect=outputs) as run:
                    with self.assertRaisesRegex(BackupError, message):
                        check_empty_target(
                            self.config, runner, "test-volume", self.image
                        )
                self.assertEqual(run.call_count, len(outputs))

    def test_post_restore_checks_compare_actual_resources_and_counts(self) -> None:
        runner = FakeRunner()
        context = ResourceContext("/data/storage", {}, None, self.image)
        report: ResourceReport = {
            "/data/storage/config/gerpgo.json": {
                "validation": "absent",
                "recovery_source": "data_volume",
            },
            "/data/storage/cache/purchase-details-v1.json": {
                "validation": "absent",
                "recovery_source": "data_volume",
            },
        }
        manifest = BackupManifest(
            "source",
            "source-volume",
            self.image,
            context.root,
            dict(runner.source_counts),
            report,
        )
        check_restored_target(self.config, runner, manifest, context, "target-volume")
        manifest.resources["/data/storage/config/gerpgo.json"]["validation"] = "passed"
        with self.assertRaisesRegex(BackupError, "运行资源与备份证据不一致"):
            check_restored_target(
                self.config, runner, manifest, context, "target-volume"
            )
        manifest.counts["users"] += 1
        with self.assertRaisesRegex(BackupError, "关键表行数不一致"):
            check_restored_target(
                self.config, runner, manifest, context, "target-volume"
            )
