from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from delivery_note.processing.models import POSITION_SOURCE_COLUMNS
from delivery_note.web.api import create_app
from delivery_note.web.database import sqlite_url
from tests.asgi_client import SyncASGIClient


class PositionApiCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.storage = self.root / "storage"
        self.app = create_app(
            database_url=sqlite_url(self.root / "api.db"),
            storage_root=self.storage,
            bootstrap_admin=("admin", "admin-pass"),
        )
        self.client = SyncASGIClient(self.app)
        self.admin_headers = self.login("admin", "admin-pass")
        operator = self.client.post(
            "/api/users",
            headers=self.admin_headers,
            json={
                "username": "operator",
                "password": "operator-pass",
                "role": "operator",
            },
        )
        self.assertEqual(operator.status_code, 201, operator.text)
        self.operator_headers = self.login("operator", "operator-pass")
        self.version = self.upload_position()
        self.valid_row = {
            "store_site": "SEEKWAY:CA",
            "jiaji_sku": "SKU-B",
            "msku": "MSKU-B",
            "scale_position": "中尾",
            "stocking_position": "备货",
        }

    def tearDown(self):
        self.client.close()
        self.app.state.database.dispose()
        self.temporary_directory.cleanup()

    def login(self, username: str, password: str) -> dict[str, str]:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['token']}"}

    @staticmethod
    def position_bytes(rows: list[list] | None = None) -> bytes:
        workbook = Workbook()
        sheet = workbook.worksheets[0]
        sheet.title = "MSKU_视图"
        sheet.append(POSITION_SOURCE_COLUMNS)
        if rows is None:
            rows = [["SEEKWAY:US", "SKU-A", "MSKU-A", "短尾", "备货", 90]]
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def upload_position(self, name: str = "position-v1") -> dict:
        response = self.client.post(
            "/api/input-versions/position",
            headers=self.admin_headers,
            data={"name": name, "activate": "true"},
            files={
                "file": (
                    f"{name}.xlsx",
                    BytesIO(self.position_bytes()),
                )
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_draft(self) -> dict:
        response = self.client.post(
            "/api/input-drafts/position",
            headers=self.admin_headers,
        )
        self.assertIn(response.status_code, {200, 201}, response.text)
        return response.json()

    def list_rows(self, draft_id: int, **params) -> dict:
        response = self.client.get(
            f"/api/input-drafts/{draft_id}/rows",
            headers=self.admin_headers,
            params=params,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
