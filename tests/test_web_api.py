from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from openpyxl import Workbook

from delivery_note.pipeline import IMPORT_COLUMNS

try:
    from delivery_note.web.api import create_app
    from delivery_note.web.models import Batch, BatchFile, ExceptionRecord
except ImportError:
    create_app = None
    Batch = None
    BatchFile = None
    ExceptionRecord = None


INPUT_KINDS = ("purchase", "product", "supplier", "position", "template")


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(create_app, "FastAPI 应用尚未实现")
        if create_app is None:
            self.skipTest("FastAPI 应用尚未实现")
        self.directory = TemporaryDirectory()
        root = Path(self.directory.name)
        self.app = create_app(
            database_url=f"sqlite+pysqlite:///{root / 'test.db'}",
            storage_root=root / "storage",
            bootstrap_admin=("admin", "admin-pass"),
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        if hasattr(self, "client"):
            self.client.close()
        if hasattr(self, "app"):
            self.app.state.database.dispose()
        if hasattr(self, "directory"):
            self.directory.cleanup()

    def login(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    def create_operator(self, admin_headers: dict[str, str]) -> dict:
        response = self.client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "username": "operator",
                "password": "operator-pass",
                "role": "operator",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    @staticmethod
    def workbook_bytes(kind: str) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        if kind == "purchase":
            sheet.append(["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"])
            sheet.append(["待交货", "KuangBiao", "SKU-A", "AMAZON:SEEKWAY:US", "水鞋-广州仓", 100])
        elif kind == "product":
            sheet.append(["SKU", "店铺/站点", "品类A", "锁仓MKSU"])
            sheet.append(["SKU-A", "SEEKWAY:US", "水鞋", "锁"])
        elif kind == "supplier":
            sheet.append(["供应商编号", "供应商名称", "状态"])
            sheet.append(["GYS-023", "KuangBiao", "启用"])
        elif kind == "position":
            sheet.title = "MSKU_视图"
            sheet.append(["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位", "已下单可售天数"])
            sheet.append(["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货", 90])
        elif kind == "template":
            sheet["A1"] = "模板提示"
            sheet.merge_cells("A1:G1")
            sheet.append(IMPORT_COLUMNS)
            sheet.append(["示例仓", "示例供应商", "示例SKU", 1, "示例站点", "", ""])
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    @staticmethod
    def delivery_bytes(quantity: int = 40) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "汇总"
        sheet.append([])
        sheet.append([])
        sheet.append([])
        sheet.append(["SKU", "US站", "总计"])
        sheet.append(["SKU-A", quantity, quantity])
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def upload_active_versions(self, headers: dict[str, str]) -> dict[str, int]:
        version_ids = {}
        for kind in INPUT_KINDS:
            response = self.client.post(
                f"/api/input-versions/{kind}",
                headers=headers,
                data={"name": f"{kind}-v1", "activate": "true"},
                files={"file": (f"{kind}.xlsx", BytesIO(self.workbook_bytes(kind)))},
            )
            self.assertEqual(response.status_code, 201, response.text)
            version_ids[kind] = response.json()["id"]
        return version_ids

    def test_login_and_admin_role_are_enforced(self):
        bad_login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(bad_login.status_code, 401)

        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        me = self.client.get("/api/auth/me", headers=admin_headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "admin")

        operator_headers = self.login("operator", "operator-pass")
        forbidden = self.client.post(
            "/api/users",
            headers=operator_headers,
            json={
                "username": "another",
                "password": "another-pass",
                "role": "operator",
            },
        )
        self.assertEqual(forbidden.status_code, 403)

        logout = self.client.post("/api/auth/logout", headers=operator_headers)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=operator_headers).status_code,
            401,
        )

    def test_input_version_activation_keeps_one_active_version(self):
        admin_headers = self.login("admin", "admin-pass")
        created_ids = []
        for name, activate in (("purchase-v1", "true"), ("purchase-v2", "false")):
            response = self.client.post(
                "/api/input-versions/purchase",
                headers=admin_headers,
                data={"name": name, "activate": activate},
                files={
                    "file": (
                        f"{name}.xlsx",
                        BytesIO(self.workbook_bytes("purchase")),
                    )
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            created_ids.append(response.json()["id"])

        activated = self.client.post(
            f"/api/input-versions/{created_ids[1]}/activate",
            headers=admin_headers,
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        versions = self.client.get(
            "/api/input-versions", headers=admin_headers
        ).json()
        active_ids = [
            version["id"]
            for version in versions
            if version["kind"] == "purchase" and version["active"]
        ]
        self.assertEqual(active_ids, [created_ids[1]])

    def test_versions_batch_order_preflight_and_compute_job(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        version_ids = self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")

        created = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "7 月交货批次"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        batch = created.json()
        self.assertEqual(batch["version_ids"], version_ids)
        batch_id = batch["id"]

        first = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={"file": ("260717-狂飙-A交货单-发货10箱.xlsx", BytesIO(self.delivery_bytes()))},
        )
        duplicate = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={"file": ("260717-狂飙-A交货单-发货10箱.xlsx", BytesIO(self.delivery_bytes()))},
        )
        second = self.client.post(
            f"/api/batches/{batch_id}/files",
            headers=operator_headers,
            files={"file": ("260717-狂飙-B交货单-发货20箱.xlsx", BytesIO(self.delivery_bytes()))},
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(second.status_code, 201, second.text)

        reordered = self.client.put(
            f"/api/batches/{batch_id}/files/order",
            headers=operator_headers,
            json={"file_ids": [second.json()["id"], first.json()["id"]]},
        )
        self.assertEqual(reordered.status_code, 200, reordered.text)
        self.assertEqual(
            [item["id"] for item in reordered.json()["files"]],
            [second.json()["id"], first.json()["id"]],
        )

        preflight = self.client.post(
            f"/api/batches/{batch_id}/preflight",
            headers=operator_headers,
        )
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertEqual(preflight.json()["status"], "preflight_ready")

        first_start = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=operator_headers,
        )
        second_start = self.client.post(
            f"/api/batches/{batch_id}/compute",
            headers=operator_headers,
        )
        self.assertEqual(first_start.status_code, 202, first_start.text)
        self.assertEqual(second_start.status_code, 202, second_start.text)
        self.assertEqual(first_start.json()["id"], second_start.json()["id"])
        self.assertEqual(first_start.json()["status"], "queued")
        job = self.client.get(
            f"/api/jobs/{first_start.json()['id']}",
            headers=operator_headers,
        )
        self.assertEqual(job.status_code, 200, job.text)
        self.assertEqual(job.json()["kind"], "compute")

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

    def test_split_review_is_quantity_safe_and_invalidates_export(self):
        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        self.upload_active_versions(admin_headers)
        operator_headers = self.login("operator", "operator-pass")
        batch_id = self.client.post(
            "/api/batches",
            headers=operator_headers,
            json={"name": "拆分测试"},
        ).json()["id"]

        with self.app.state.database.session() as session:
            batch = session.get(Batch, batch_id)
            batch.status = "succeeded"
            source = BatchFile(
                batch_id=batch_id,
                original_name="260717-狂飙-A交货单-发货10箱.xlsx",
                storage_path="unused.xlsx",
                file_order=1,
                supplier_name="KuangBiao",
                supplier_code="GYS-023",
                delivery_total=40,
                import_total=0,
                manual_total=40,
                document_note="260717-狂飙-01-10箱",
                import_rows=[],
            )
            session.add(source)
            session.flush()
            exception = ExceptionRecord(
                batch_file_id=source.id,
                sku="SKU-A",
                original_site="US",
                full_site="AMAZON:SEEKWAY:US",
                destination="水鞋-广州仓",
                delivery_quantity=40,
                allocated_quantity=0,
                manual_quantity=40,
                reason="超出采购未交量",
                status="pending",
            )
            session.add(exception)
            session.commit()
            exception_id = exception.id

        invalid = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={"parts": [{"quantity": 39, "resolved": False}]},
        )
        self.assertEqual(invalid.status_code, 400)

        valid = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={
                "parts": [
                    {"quantity": 25, "destination": "仓A", "resolved": True},
                    {"quantity": 15, "destination": "仓B", "resolved": False},
                ]
            },
        )
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["status"], "partial")
        self.assertEqual(
            [part["quantity"] for part in valid.json()["parts"]],
            [25, 15],
        )
        summary = self.client.get(
            f"/api/batches/{batch_id}", headers=operator_headers
        ).json()["summary"]
        self.assertEqual(
            (summary["delivery_total"], summary["import_total"], summary["manual_total"]),
            (40, 25, 15),
        )

        export = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=operator_headers,
        )
        repeated = self.client.post(
            f"/api/batches/{batch_id}/export",
            headers=operator_headers,
        )
        self.assertEqual(export.status_code, 202, export.text)
        self.assertEqual(export.json()["id"], repeated.json()["id"])
        blocked_split = self.client.put(
            f"/api/exceptions/{exception_id}/split",
            headers=operator_headers,
            json={"parts": [{"quantity": 40, "resolved": False}]},
        )
        self.assertEqual(blocked_split.status_code, 409)


if __name__ == "__main__":
    unittest.main()