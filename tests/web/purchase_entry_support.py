"""采购接口测试使用的合成资料。"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from tests.purchase_entry.support import make_files
from tests.support.web_api import WebApiCase


def workbook_payload(rows: list[list[object]], title: str = "Sheet") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet.title = title
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class PurchaseEntryCase(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        fixtures = self.root / "purchase-fixtures"
        fixtures.mkdir()
        self.purchase_files = make_files(fixtures)

    def upload_purchase_inputs(self, headers: dict[str, str]) -> dict[str, int]:
        payloads = {
            "supplier": self.supplier_workbook_bytes(
                [["SUP001", "供应商甲公司", "启用", "供应商甲|甲厂"]]
            ),
            "product": self.purchase_files["product"].read_bytes(),
            "sku_warehouse": self.purchase_files["warehouse"].read_bytes(),
        }
        versions = self.client.get("/api/input-versions", headers=headers).json()
        result = {
            version["kind"]: version["id"]
            for version in versions
            if version["kind"] == "purchase_template" and version["active"]
        }
        for kind, payload in payloads.items():
            response = self.client.post(
                f"/api/input-versions/{kind}",
                headers=headers,
                data={"name": f"{kind}-v1", "activate": "true"},
                files={"file": (f"{kind}.xlsx", BytesIO(payload))},
            )
            self.assertEqual(response.status_code, 201, response.text)
            result[kind] = response.json()["id"]
        return result
