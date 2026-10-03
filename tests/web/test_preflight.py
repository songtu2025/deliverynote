from tests.support.web_api import WebApiCase
from io import BytesIO
from unittest.mock import patch


import delivery_note.web.batch_preflight as batch_preflight_module


class WebApiTests(WebApiCase):
    def test_preflight_rejects_file_order_changed_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        batch_id = self.client.post(
            "/api/batches", headers=headers, json={"name": "预检并发测试"}
        ).json()["id"]
        file_ids = []
        for name in (
            "260717-狂飙-A交货单.xlsx",
            "260717-狂飙-B交货单.xlsx",
        ):
            response = self.client.post(
                f"/api/batches/{batch_id}/files",
                headers=headers,
                files={"file": (name, BytesIO(self.delivery_bytes()))},
            )
            self.assertEqual(response.status_code, 201, response.text)
            file_ids.append(response.json()["id"])

        original_reader = batch_preflight_module.read_delivery_workbook
        reordered = False

        def read_and_reorder(path):
            nonlocal reordered
            if not reordered:
                reordered = True
                response = self.client.put(
                    f"/api/batches/{batch_id}/files/order",
                    headers=headers,
                    json={"file_ids": list(reversed(file_ids))},
                )
                self.assertEqual(response.status_code, 200, response.text)
            return original_reader(path)

        with patch.object(
            batch_preflight_module,
            "read_delivery_workbook",
            side_effect=read_and_reorder,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=headers).json()[
                "status"
            ],
            "draft",
        )
        compute = self.client.post(f"/api/batches/{batch_id}/compute", headers=headers)
        self.assertEqual(compute.status_code, 409, compute.text)

    def test_preflight_rejects_file_removed_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        batch_id = self.client.post(
            "/api/batches", headers=headers, json={"name": "预检删除测试"}
        ).json()["id"]
        uploaded = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=headers,
            files={
                "file": (
                    "260717-狂飙-A交货单.xlsx",
                    BytesIO(self.delivery_bytes()),
                )
            },
        ).json()
        original_reader = batch_preflight_module.read_delivery_workbook

        def read_and_remove(path):
            removed = self.client.delete(
                f"/api/batches/{batch_id}/files/{uploaded['id']}",
                headers=headers,
            )
            self.assertEqual(removed.status_code, 200, removed.text)
            return original_reader(path)

        with patch.object(
            batch_preflight_module,
            "read_delivery_workbook",
            side_effect=read_and_remove,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        self.assertEqual(
            self.client.get(f"/api/batches/{batch_id}", headers=headers).json()[
                "status"
            ],
            "draft",
        )

    def test_preflight_rejects_inbound_replacement_during_validation(self):
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        created = self.client.post(
            "/api/self-operated-batches",
            headers=headers,
            data={"name": "自营仓预检并发测试"},
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
        batch_id = created.json()["id"]
        original_reader = batch_preflight_module.read_self_operated_delivery_workbook

        def read_and_replace(path):
            result = original_reader(path)
            replaced = self.client.post(
                f"/api/self-operated-batches/{batch_id}/inbound-file",
                headers=headers,
                files={
                    "file": (
                        "更新后的收货入库单.xlsx",
                        BytesIO(self.self_operated_inbound_bytes()),
                    )
                },
            )
            self.assertEqual(replaced.status_code, 200, replaced.text)
            return result

        with patch.object(
            batch_preflight_module,
            "read_self_operated_delivery_workbook",
            side_effect=read_and_replace,
        ):
            preflight = self.client.post(
                f"/api/batches/{batch_id}/preflight", headers=headers
            )
        self.assertEqual(preflight.status_code, 409, preflight.text)
        batch = self.client.get(f"/api/batches/{batch_id}", headers=headers).json()
        self.assertEqual(batch["status"], "draft")
        self.assertEqual(
            batch["inbound_file"]["original_name"], "更新后的收货入库单.xlsx"
        )

    def test_preflight_rejects_invalid_excel_content(self):
        admin_headers = self.login("admin", "admin-pass")
        self.upload_active_versions(admin_headers)
        created = self.client.post(
            "/api/batches",
            headers=admin_headers,
            json={"name": "无效预检"},
        )
        batch_id = created.json()["id"]
        uploaded = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=admin_headers,
            files={"file": ("260717-狂飙-A交货单-发货10箱.xlsx", BytesIO(b"invalid"))},
        )
        self.assertEqual(uploaded.status_code, 201)

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=admin_headers,
        )
        self.assertEqual(preflight.status_code, 400)
        batch = self.client.get(
            f"/api/batches/{batch_id}", headers=admin_headers
        ).json()
        self.assertEqual(batch["status"], "draft")
