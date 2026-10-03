from tests.support.web_api import WebApiCase
from io import BytesIO


class WebApiTests(WebApiCase):
    def test_self_operated_batch_only_requires_its_own_input_versions(self):
        headers = self.login("admin", "admin-pass")
        version_ids = {}
        for kind in ("product", "supplier"):
            response = self.client.post(
                f"/api/input-versions/{kind}",
                headers=headers,
                data={"name": f"{kind}-self-operated", "activate": "true"},
                files={
                    "file": (
                        f"{kind}.xlsx",
                        BytesIO(self.workbook_bytes(kind)),
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            version_ids[kind] = response.json()["id"]

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "不依赖原流程资料的自营仓批次"},
            files={
                "delivery_file": (
                    "质检交货单.xlsx",
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
        self.assertEqual(batch["version_ids"]["product"], version_ids["product"])
        self.assertEqual(batch["version_ids"]["supplier"], version_ids["supplier"])
        self.assertIsNone(batch["version_ids"]["purchase"])
        self.assertIsNone(batch["version_ids"]["position"])
        self.assertIsNone(batch["version_ids"]["template"])
        self.assertIn("inbound_template", batch["versions"])
        self.assertEqual(batch["file_count"], 1)
        self.assertTrue(batch["inbound_file"]["uploaded"])

        delivery_batch = self.client.post(
            "/api/batches",
            headers=headers,
            json={"name": "原流程仍要求完整资料"},
        )
        self.assertEqual(delivery_batch.status_code, 409, delivery_batch.text)
        self.assertIn("purchase", delivery_batch.json()["detail"])
        self.assertIn("position", delivery_batch.json()["detail"])
        self.assertNotIn("template", delivery_batch.json()["detail"])

    def test_self_operated_creation_accepts_repeated_delivery_file_fields(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "多质检单批次"},
            files=[
                (
                    "delivery_file",
                    (
                        "260817-狂飙-A质检交货单.xlsx",
                        BytesIO(self.self_operated_delivery_bytes(8)),
                    ),
                ),
                (
                    "delivery_file",
                    (
                        "260817-狂飙-B质检交货单.xlsx",
                        BytesIO(self.self_operated_delivery_bytes(7)),
                    ),
                ),
                (
                    "inbound_file",
                    (
                        "自营仓收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    ),
                ),
            ],
        )

        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(batch["file_count"], 2)
        self.assertEqual(
            [
                (source["original_name"], source["file_order"])
                for source in batch["files"]
            ],
            [
                ("260817-狂飙-A质检交货单.xlsx", 1),
                ("260817-狂飙-B质检交货单.xlsx", 2),
            ],
        )

    def test_self_operated_multi_file_creation_is_atomic_on_validation_failure(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)

        invalid = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "多质检单原子失败"},
            files=[
                (
                    "delivery_file",
                    (
                        "260817-狂飙-A质检交货单.xlsx",
                        BytesIO(self.self_operated_delivery_bytes()),
                    ),
                ),
                (
                    "delivery_file",
                    ("260817-狂飙-B质检交货单.xlsx", BytesIO(b"invalid")),
                ),
                (
                    "inbound_file",
                    (
                        "自营仓收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    ),
                ),
            ],
        )

        self.assertEqual(invalid.status_code, 400, invalid.text)
        self.assertEqual(self.client.get("/api/batches", headers=headers).json(), [])
        temporary_root = (
            self.app.state.storage_root / "temporary" / "self-operated-batches"
        )
        self.assertEqual(list(temporary_root.glob("*")), [])

    def test_self_operated_creation_rejects_duplicate_names_and_file_limit(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        duplicate_files = [
            (
                "delivery_file",
                ("同名质检单.xlsx", BytesIO(self.self_operated_delivery_bytes())),
            ),
            (
                "delivery_file",
                ("同名质检单.xlsx", BytesIO(self.self_operated_delivery_bytes())),
            ),
            (
                "inbound_file",
                (
                    "自营仓收货入库单.xlsx",
                    BytesIO(self.self_operated_inbound_bytes()),
                ),
            ),
        ]

        duplicate = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "同名失败"},
            files=duplicate_files,
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertIn("同名", duplicate.json()["detail"])

        self.app.state.max_batch_upload_files = 1
        limited = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "数量超限"},
            files=[
                (
                    "delivery_file",
                    ("A.xlsx", BytesIO(self.self_operated_delivery_bytes())),
                ),
                (
                    "delivery_file",
                    ("B.xlsx", BytesIO(self.self_operated_delivery_bytes())),
                ),
                (
                    "inbound_file",
                    (
                        "自营仓收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    ),
                ),
            ],
        )
        self.assertEqual(limited.status_code, 413, limited.text)
        self.assertEqual(self.client.get("/api/batches", headers=headers).json(), [])
