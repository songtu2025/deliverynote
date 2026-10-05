from datetime import datetime
from io import BytesIO
from unittest.mock import patch

from delivery_note.web import input_version_routes
from delivery_note.web.models import InputVersion
from tests.support.web_api import WebApiCase


class InputVersionCommandTests(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.headers = self.login("admin", "admin-pass")
        self.version_ids = self.upload_active_versions(self.headers)

    def test_version_list_is_readable_but_writes_require_admin(self) -> None:
        self.create_operator(self.headers)
        operator_headers = self.login("operator", "operator-pass")
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        master = self.app.state.storage_root / "master"
        files_before = {path for path in master.rglob("*") if path.is_file()}
        for headers, expected in (({}, 401), (operator_headers, 403)):
            with self.subTest(expected=expected):
                uploaded = self.client.post(
                    "/api/input-versions/purchase",
                    headers=headers,
                    data={"name": "denied-version", "activate": "true"},
                    files={
                        "file": (
                            "purchase.xlsx",
                            BytesIO(self.workbook_bytes("purchase")),
                        )
                    },
                )
                activated = self.client.post(
                    f"/api/input-versions/{self.version_ids['purchase']}/activate",
                    headers=headers,
                )
                self.assertEqual(uploaded.status_code, expected, uploaded.text)
                self.assertEqual(activated.status_code, expected, activated.text)
        self.assertEqual(self.client.get("/api/input-versions").status_code, 401)
        listed = self.client.get("/api/input-versions", headers=operator_headers)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json(), before)
        self.assertEqual(
            {path for path in master.rglob("*") if path.is_file()}, files_before
        )

    def test_upload_defaults_and_activation_preserve_response_fields(self) -> None:
        admin = self.client.get("/api/auth/me", headers=self.headers).json()
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        other_active = {
            item["kind"]: item["id"]
            for item in before
            if item["active"] and item["kind"] != "purchase"
        }
        created: list[dict[str, object]] = []
        for name, activate in (("purchase-default", False), ("purchase-current", True)):
            data = {"name": name}
            if activate:
                data["activate"] = "true"
            response = self.client.post(
                "/api/input-versions/purchase",
                headers=self.headers,
                data=data,
                files={
                    "file": ("purchase.xlsx", BytesIO(self.workbook_bytes("purchase")))
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            version = response.json()
            self.assertEqual(
                set(version),
                {
                    "id",
                    "kind",
                    "name",
                    "original_name",
                    "active",
                    "created_by",
                    "created_at",
                },
            )
            self.assertEqual(version["kind"], "purchase")
            self.assertEqual(version["name"], name)
            self.assertEqual(version["original_name"], "purchase.xlsx")
            self.assertEqual(version["created_by"], admin["id"])
            self.assertEqual(version["active"], activate)
            self.assertTrue(version["created_at"].endswith("Z"))
            created.append(version)
            listed = self.client.get("/api/input-versions", headers=self.headers).json()
            expected_id = version["id"] if activate else self.version_ids["purchase"]
            self.assertEqual(
                [
                    item["id"]
                    for item in listed
                    if item["kind"] == "purchase" and item["active"]
                ],
                [expected_id],
            )
            self.assertEqual(
                {
                    item["kind"]: item["id"]
                    for item in listed
                    if item["active"] and item["kind"] != "purchase"
                },
                other_active,
            )
        activated = self.client.post(
            f"/api/input-versions/{created[0]['id']}/activate", headers=self.headers
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json(), created[0] | {"active": True})
        listed = self.client.get("/api/input-versions", headers=self.headers).json()
        self.assertEqual(
            [
                item["id"]
                for item in listed
                if item["kind"] == "purchase" and item["active"]
            ],
            [created[0]["id"]],
        )

    def test_version_list_orders_by_kind_then_creation_time(self) -> None:
        with self.app.state.database.session() as session:
            base = session.get(InputVersion, self.version_ids["purchase"])
            base.created_at = datetime(2026, 1, 1)
            newer = InputVersion(
                kind="purchase",
                name="purchase-newer",
                original_name=base.original_name,
                storage_path=base.storage_path,
                active=False,
                created_by=base.created_by,
                created_at=datetime(2026, 1, 2),
            )
            session.add(newer)
            session.commit()
            expected_ids = [newer.id, base.id]
        response = self.client.get("/api/input-versions", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        versions = response.json()
        kinds = [item["kind"] for item in versions]
        self.assertEqual(kinds, sorted(kinds))
        self.assertEqual(
            [item["id"] for item in versions if item["kind"] == "purchase"],
            expected_ids,
        )
        self.assertEqual(
            [item["created_at"] for item in versions if item["kind"] == "purchase"],
            ["2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z"],
        )

    def test_upload_unique_conflict_rolls_back_version_and_file(self) -> None:
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        audits_before = self.client.get("/api/audit-logs", headers=self.headers).json()
        master = self.app.state.storage_root / "master"
        files_before = {path for path in master.rglob("*") if path.is_file()}
        # 模拟预检查后出现同名版本，由真实数据库唯一约束触发冲突。
        with patch.object(
            input_version_routes, "validate_new_input_version", return_value=None
        ):
            response = self.client.post(
                "/api/input-versions/purchase",
                headers=self.headers,
                data={"name": "purchase-v1", "activate": "true"},
                files={
                    "file": ("conflict.xlsx", BytesIO(self.workbook_bytes("purchase")))
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"], "输入版本发生并发冲突，请刷新后重试"
        )
        self.assertEqual(
            self.client.get("/api/input-versions", headers=self.headers).json(), before
        )
        self.assertEqual(
            self.client.get("/api/audit-logs", headers=self.headers).json(),
            audits_before,
        )
        self.assertEqual(
            {path for path in master.rglob("*") if path.is_file()}, files_before
        )

    def test_missing_version_activation_returns_404_without_changes(self) -> None:
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        response = self.client.post(
            "/api/input-versions/999/activate", headers=self.headers
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["detail"], "输入版本不存在")
        self.assertEqual(
            self.client.get("/api/input-versions", headers=self.headers).json(), before
        )
