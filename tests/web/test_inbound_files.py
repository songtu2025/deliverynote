from tests.support.web_api import WebApiCase
from io import BytesIO
from pathlib import Path
from unittest.mock import patch


from delivery_note.web.models import (
    Batch,
    SelfOperatedBatch,
)


class WebApiTests(WebApiCase):
    def test_inbound_upload_checks_batch_kind_before_editable_status(self) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        ordinary = self.client.post(
            "/api/batches", headers=headers, json={"name": "普通批次"}
        ).json()
        inbound = self.client.post(
            "/api/self-operated-batches", headers=headers, json={"name": "自营批次"}
        ).json()
        with self.app.state.database.session() as session:
            for batch_id in (ordinary["id"], inbound["id"]):
                batch = session.get(Batch, batch_id)
                assert batch is not None
                batch.status = "running"
            session.commit()
        for batch, status, detail in (
            (ordinary, 404, "自营仓入库批次不存在"),
            (inbound, 409, "当前批次状态不可修改文件"),
        ):
            with self.subTest(batch_id=batch["id"]):
                response = self.client.post(
                    f"/api/self-operated-batches/{batch['id']}/inbound-file",
                    headers=headers,
                    files={"file": ("入库单.xlsx", BytesIO(b"invalid"))},
                )
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.json(), {"detail": detail})
                self.assertFalse(
                    (self.root / "storage" / "batches" / str(batch["id"])).exists()
                )

    def test_self_operated_batch_locks_rule_and_accepts_an_appended_delivery(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        template = self.client.post(
            "/api/input-versions/inbound_template",
            headers=headers,
            data={"name": "inbound-template-v1", "activate": "true"},
            files={
                "file": (
                    "inbound-template.xlsx",
                    BytesIO(self.workbook_bytes("inbound_template")),
                )
            },
        )
        self.assertEqual(template.status_code, 201, template.text)
        rule = self.client.post(
            "/api/self-operated-overreceipt-rule-versions",
            headers=headers,
            json={"name": "自营仓超收 5 件", "allowance": 5},
        )
        self.assertEqual(rule.status_code, 201, rule.text)

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "自营仓入库接口测试"},
            files={
                "delivery_file": (
                    "260817-狂飙-质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        batch_id = batch["id"]
        self.assertEqual(batch["workflow"], "self_operated_inbound")
        self.assertEqual(batch["self_operated_overreceipt_rule"]["allowance"], 5)
        self.assertEqual(
            batch["versions"]["inbound_template"]["id"],
            template.json()["id"],
        )
        self.assertEqual(batch["file_count"], 1)
        self.assertTrue(batch["inbound_file"]["uploaded"])
        listed_batch = next(
            item
            for item in self.client.get("/api/batches", headers=headers).json()
            if item["id"] == batch_id
        )
        self.assertEqual(
            listed_batch,
            {key: batch[key] for key in listed_batch},
        )
        self.app.state.max_batch_upload_files = 2
        extra_file = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={
                "file": (
                    "260817-狂飙-额外质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                )
            },
        )
        self.assertEqual(extra_file.status_code, 201, extra_file.text)
        self.assertEqual(extra_file.json()["file_order"], 2)
        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")
        self.assertEqual(preflight.json()["file_count"], 2)

    def test_self_operated_preflight_validates_every_delivery_file(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "逐份预检"},
            files={
                "delivery_file": (
                    "260817-狂飙-A质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        batch_id = created.json()["id"]
        appended = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={"file": ("第二份损坏.xlsx", BytesIO(b"invalid"))},
        )
        self.assertEqual(appended.status_code, 201, appended.text)

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=headers,
        )

        self.assertEqual(preflight.status_code, 400, preflight.text)
        self.assertIn("第二份", preflight.json()["detail"])

    def test_inbound_replacement_succeeds_when_old_file_cleanup_fails(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "入库单清理失败"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": (
                    "旧入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch_id = created.json()["id"]
        with self.app.state.database.session() as session:
            old_path = Path(
                session.get(SelfOperatedBatch, batch_id).inbound_storage_path
            )

        original_unlink = Path.unlink

        def fail_old_file_cleanup(path, *args, **kwargs):
            if path == old_path:
                raise PermissionError("denied")
            return original_unlink(path, *args, **kwargs)

        with (
            patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=fail_old_file_cleanup,
            ),
            self.assertLogs("delivery_note.web.api", level="WARNING"),
        ):
            replaced = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=headers,
                files={
                    "file": (
                        "新入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    )
                },
            )

        self.assertEqual(replaced.status_code, 200, replaced.text)
        with self.app.state.database.session() as session:
            profile = session.get(SelfOperatedBatch, batch_id)
            self.assertEqual(profile.inbound_original_name, "新入库单.xlsx")
            self.assertNotEqual(Path(profile.inbound_storage_path), old_path)
            self.assertTrue(Path(profile.inbound_storage_path).is_file())
        self.assertTrue(old_path.is_file())

    def test_self_operated_creation_is_atomic_when_file_validation_fails(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        invalid = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "校验失败的自营仓批次"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
                    BytesIO(self.self_operated_delivery_bytes()),
                ),
                "inbound_file": ("异常入库单.xlsx", BytesIO(b"not-an-excel-file")),
            },
        )
        self.assertEqual(invalid.status_code, 400, invalid.text)

        batches = self.client.get("/api/batches", headers=headers)
        self.assertEqual(batches.status_code, 200, batches.text)
        self.assertEqual(batches.json(), [])
        temporary_root = (
            self.app.state.storage_root / "temporary" / "self-operated-batches"
        )
        self.assertEqual(list(temporary_root.glob("*")), [])
