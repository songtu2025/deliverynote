from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select

from delivery_note.web.models import (
    AuditLog,
    Batch,
    BatchFile,
    InputVersion,
    SelfOperatedBatch,
)
from tests.support.web_api import WebApiCase


class BatchCreationRollbackTests(WebApiCase):
    def assert_no_batch_files(self) -> None:
        with self.app.state.database.session() as session:
            for model in (Batch, BatchFile, SelfOperatedBatch):
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(model)), 0
                )
            self.assertEqual(
                session.scalar(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.action.in_(
                            ["create_batch_with_files", "create_self_operated_batch"]
                        )
                    )
                ),
                0,
            )
        storage = self.app.state.storage_root
        for directory in (storage / "batches", storage / "temporary"):
            self.assertEqual([p for p in directory.rglob("*") if p.is_file()], [])

    def test_commit_failure_removes_created_delivery_and_inbound_files(self) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        for inbound in (False, True):
            with self.subTest(inbound=inbound):
                if inbound:
                    route, message = "self-operated-batches", "自营仓文件校验失败"
                    files = {
                        "delivery_file": (
                            "质检.xlsx",
                            self.self_operated_delivery_bytes(),
                        ),
                        "inbound_file": (
                            "入库.xlsx",
                            self.self_operated_inbound_bytes(),
                        ),
                    }
                else:
                    route, message = "batches/with-files", "交货文件校验失败"
                    files = {"files": ("交货.xlsx", self.delivery_bytes())}
                with patch(
                    "sqlalchemy.orm.Session.commit",
                    side_effect=ValueError("模拟提交失败"),
                ) as commit:
                    response = self.client.post(
                        f"/api/{route}",
                        headers=headers,
                        data={"name": "提交失败的批次"},
                        files={
                            key: (name, BytesIO(data))
                            for key, (name, data) in files.items()
                        },
                    )
                commit.assert_called_once()
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"], f"{message}：模拟提交失败")
                self.assert_no_batch_files()

    def test_failed_creation_keeps_shared_api_inbound_version_file(self) -> None:
        headers = self.login("admin", "admin-pass")
        self.upload_active_versions(headers)
        shared = Path(self.root) / "shared-inbound.xlsx"
        content = self.self_operated_inbound_bytes()
        shared.write_bytes(content)
        with self.app.state.database.session() as session:
            version = InputVersion(
                kind="self_operated_inbound",
                name="共享待入库版本",
                original_name=shared.name,
                storage_path=str(shared),
                active=True,
                created_by=1,
            )
            session.add(version)
            session.commit()
            version_id = version.id
        with patch(
            "sqlalchemy.orm.Session.commit", side_effect=ValueError("模拟提交失败")
        ) as commit:
            response = self.client.post(
                "/api/self-operated-batches",
                headers=headers,
                data={"name": "共享来源回滚"},
                files={
                    "delivery_file": (
                        "质检.xlsx",
                        BytesIO(self.self_operated_delivery_bytes()),
                    )
                },
            )
        commit.assert_called_once()
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "自营仓文件校验失败：模拟提交失败")
        self.assert_no_batch_files()
        self.assertEqual(shared.read_bytes(), content)
        downloaded = self.client.get(
            f"/api/input-versions/{version_id}/download", headers=headers
        )
        self.assertEqual(downloaded.status_code, 200, downloaded.text)
        self.assertEqual(downloaded.content, content)
