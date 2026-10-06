"""复用真实模型工厂，为存储审计构造隔离引用和文件。"""

import hashlib
from pathlib import Path

from sqlalchemy import select, update

from delivery_note.web.models import (
    Batch,
    BatchFile,
    InputVersion,
    Job,
    SelfOperatedBatch,
)
from tests.support import postgres as postgres_cases
from tests.support.web_api import WebApiCase


class StorageAuditCase(WebApiCase):
    def setUp(self) -> None:
        super().setUp()
        self.storage = self.root / "storage"
        self.url = str(self.app.state.database.engine.url)
        with self.app.state.database.session() as session:
            session.execute(update(InputVersion).values(active=False))
            user, batch, _ = postgres_cases.PostgreSQLCase.create_batch(
                session, "审计样本", username="audit-owner"
            )
            self.user_id, self.batch_id = user.id, batch.id
            for version in session.scalars(select(InputVersion)):
                version.storage_path = str(self.file(f"master/{version.kind}.xlsx"))
            session.commit()

    def file(self, name: str) -> Path:
        path = self.storage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes("只核验文件状态".encode("utf-8"))
        return path

    def seed_outputs(self) -> Path:
        published = self.storage / f"batches/{self.batch_id}/exports/export-{'a' * 32}"
        archive = self.file(str(published.relative_to(self.storage) / "batch.zip"))
        self.file(
            str(
                published.relative_to(self.storage)
                / f"batch-{self.batch_id}-merged.xlsx"
            )
        )
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            batch.zip_path = str(archive)
            session.add(
                Job(
                    batch_id=self.batch_id,
                    kind="export",
                    status="succeeded",
                    output_path=str(archive),
                )
            )
            for order in (0, 1):
                session.add(
                    BatchFile(
                        batch_id=self.batch_id,
                        file_order=order,
                        original_name=f"source{order}.xlsx",
                        storage_path=str(
                            self.file(f"batches/{self.batch_id}/inputs/{order}.xlsx")
                        ),
                        result_path=str(
                            self.file(
                                str(
                                    published.relative_to(self.storage)
                                    / f"result{order}.xlsx"
                                )
                            )
                        ),
                    )
                )
            session.add(
                InputVersion(
                    kind="inbound_template",
                    name="入库模板",
                    original_name="模板.xlsx",
                    storage_path=str(self.file("master/inbound_template.xlsx")),
                    created_by=self.user_id,
                )
            )
            session.flush()
            inbound_template = session.scalar(
                select(InputVersion.id).where(InputVersion.kind == "inbound_template")
            )
            session.add(
                SelfOperatedBatch(
                    batch_id=self.batch_id,
                    template_version_id=inbound_template,
                    inbound_storage_path=str(self.file("shared/inbound.xlsx")),
                )
            )
            session.add(
                InputVersion(
                    kind="purchase",
                    name="未激活历史版本",
                    original_name="历史.xlsx",
                    active=False,
                    storage_path=str(self.file("master/inactive.xlsx")),
                    created_by=self.user_id,
                )
            )
            session.commit()
        return published

    def candidates(self) -> tuple[Path, Path, Path]:
        directory = self.storage / f"batches/{self.batch_id}/exports/.tmp-{'b' * 32}"
        directory.mkdir(parents=True)
        purchase = self.file(
            "master/purchase/purchase_sync_91_积加采购数据_20261006_120000.xlsx"
        )
        inbound = self.file(
            "master/self_operated_inbound/self_operated_inbound_sync_92_积加待入库数据_20261006_120000.xlsx"
        )
        return directory, purchase, inbound

    def snapshot_files(self) -> dict[str, tuple[str, int]]:
        return {
            str(path.relative_to(self.root)): (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
            for path in self.root.rglob("*")
            if path.is_file()
        }
