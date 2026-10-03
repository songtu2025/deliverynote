"""按资料类型验证上传格式，以及失败后的文件和版本状态。"""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from httpx2 import Response

from delivery_note.web import input_version_routes
from tests.support.web_api import WebApiCase

REGULAR_KINDS = ("purchase", "product", "supplier", "position")
TEMPLATE_MESSAGES = {
    "template": "导出模板仅支持 .xlsx 文件",
    "inbound_template": "积加入库模板仅支持 .xlsx 文件",
}
FIXTURES = Path(__file__).parents[1] / "fixtures"


class InputUploadFormatTests(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.headers = self.login("admin", "admin-pass")

    def _upload(self, kind: str, filename: str, payload: bytes) -> Response:
        return self.client.post(
            f"/api/input-versions/{kind}",
            headers=self.headers,
            data={"name": filename, "activate": "true"},
            files={"file": (filename, BytesIO(payload))},
        )

    def test_template_formats_are_rejected_before_saving_or_parsing(self) -> None:
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        with (
            patch.object(
                input_version_routes,
                "_save_upload",
                wraps=input_version_routes._save_upload,
            ) as save,
            patch.object(
                input_version_routes,
                "_validate_input_version",
                wraps=input_version_routes._validate_input_version,
            ) as parse,
        ):
            for kind, message in TEMPLATE_MESSAGES.items():
                for suffix in (".xls", ".XLS", ".csv", ".xlsm", ""):
                    with self.subTest(kind=kind, suffix=suffix):
                        response = self._upload(
                            kind,
                            f"unsupported{suffix}",
                            (FIXTURES / "supplier_minimal.xls").read_bytes(),
                        )
                        self.assertEqual(response.status_code, 400, response.text)
                        self.assertEqual(response.json()["detail"], message)
            save.assert_not_called()
            parse.assert_not_called()
        self.assertEqual(
            self.client.get("/api/input-versions", headers=self.headers).json(),
            before,
        )
        self.assertEqual(list((self.app.state.storage_root / "master").rglob("*")), [])

    def test_regular_formats_keep_existing_active_versions_when_rejected(self) -> None:
        for kind in REGULAR_KINDS:
            uploaded = self._upload(
                kind, f"active-{kind}.xlsx", self.workbook_bytes(kind)
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        master = self.app.state.storage_root / "master"
        files_before = sorted(path for path in master.rglob("*") if path.is_file())
        for kind in REGULAR_KINDS:
            for suffix in (".csv", ".xlsm", ""):
                with self.subTest(kind=kind, suffix=suffix):
                    response = self._upload(kind, f"unsupported{suffix}", b"invalid")
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertEqual(
                        response.json()["detail"], "仅支持 .xls、.xlsx 文件"
                    )
        self.assertEqual(
            self.client.get("/api/input-versions", headers=self.headers).json(),
            before,
        )
        self.assertEqual(
            sorted(path for path in master.rglob("*") if path.is_file()), files_before
        )

    def test_all_kinds_accept_valid_uppercase_xlsx(self) -> None:
        for kind in (*REGULAR_KINDS, *TEMPLATE_MESSAGES):
            with self.subTest(kind=kind):
                response = self._upload(
                    kind, f"valid-{kind}.XLSX", self.workbook_bytes(kind)
                )
                self.assertEqual(response.status_code, 201, response.text)
                self.assertTrue(response.json()["active"])
                version_id = response.json()["id"]
                result = self.client.get(
                    f"/api/input-versions/{version_id}/inspection", headers=self.headers
                )
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["summary"]["row_count"], 1)
                self.assertEqual(result.json()["preview"]["total"], 1)

    def test_regular_kinds_accept_native_xls(self) -> None:
        for kind in REGULAR_KINDS:
            payload = (FIXTURES / f"{kind}_minimal.xls").read_bytes()
            self.assertEqual(payload[:8], bytes.fromhex("d0cf11e0a1b11ae1"))
            suffixes = (".XLS",) if kind == "position" else (".xls", ".XLS")
            for suffix in suffixes:
                with self.subTest(kind=kind, suffix=suffix):
                    response = self._upload(kind, f"native-{kind}{suffix}", payload)
                    self.assertEqual(response.status_code, 201, response.text)
                    version_id = response.json()["id"]
                    result = self.client.get(
                        f"/api/input-versions/{version_id}/inspection",
                        headers=self.headers,
                    )
                    self.assertEqual(result.status_code, 200, result.text)
                    self.assertEqual(result.json()["summary"]["row_count"], 1)
                    row = result.json()["preview"]["rows"][0]
                    column = (
                        "供应商编号"
                        if kind == "supplier"
                        else ("积加SKU" if kind == "position" else "SKU")
                    )
                    self.assertEqual(
                        row[column], "GYS-027" if kind == "supplier" else "SKU-A"
                    )

    def test_allowed_formats_still_enforce_version_and_position_rules(self) -> None:
        for kind in ("purchase", "position"):
            filename = f"first-{kind}.xlsx"
            payload = self.workbook_bytes(kind)
            first = self._upload(kind, filename, payload)
            self.assertEqual(first.status_code, 201, first.text)
            before = self.client.get("/api/input-versions", headers=self.headers).json()
            repeated = self._upload(kind, filename, payload)
            self.assertEqual(repeated.status_code, 409, repeated.text)
            self.assertEqual(repeated.json()["detail"], "版本名称已存在")
            if kind == "position":
                replacement = self._upload(
                    kind,
                    "replacement.xls",
                    (FIXTURES / "position_minimal.xls").read_bytes(),
                )
                self.assertEqual(replacement.status_code, 409, replacement.text)
                self.assertIn("通过草稿流程发布新版本", replacement.json()["detail"])
            self.assertEqual(
                self.client.get("/api/input-versions", headers=self.headers).json(),
                before,
            )
        unknown = self._upload("unknown", "invalid.csv", b"invalid")
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()["detail"], "输入类型不存在")

    def test_corrupt_allowed_formats_leave_no_files_or_versions(self) -> None:
        before = self.client.get("/api/input-versions", headers=self.headers).json()
        for kind in (*REGULAR_KINDS, *TEMPLATE_MESSAGES):
            suffixes = (".xls", ".xlsx") if kind in REGULAR_KINDS else (".xlsx",)
            for suffix in suffixes:
                with self.subTest(kind=kind, suffix=suffix):
                    response = self._upload(
                        kind, f"broken{suffix}", b"not-an-excel-file"
                    )
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIn("输入版本校验失败", response.json()["detail"])
        self.assertEqual(
            self.client.get("/api/input-versions", headers=self.headers).json(), before
        )
        master = self.app.state.storage_root / "master"
        self.assertEqual([path for path in master.rglob("*") if path.is_file()], [])
