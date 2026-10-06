"""复用真实交货计算与审校，准备隔离的缺失合并表场景。"""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from sqlalchemy import select

from delivery_note.web.batch_views import merged_export_path
from delivery_note.web.models import Batch, BatchFile
from delivery_note.worker import run_once
from scripts.backup.archive import sha256
from tests.support.delivery_exports import SPLIT_PARTS
from tests.support.worker import WorkerCase


class MergedRecoveryCase(WorkerCase):
    def setUp(self) -> None:
        super().setUp()
        first = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 80
        )
        second = self.create_delivery(
            self.root / "260717-狂飙-B交货单-发货20箱.xlsx", 80
        )
        self.batch_id, identifier = self.create_batch([first, second])
        self.assertEqual(run_once(self.database_url, self.storage_root), identifier)
        exceptions = self.client.get(
            f"/api/batches/{self.batch_id}/exceptions", headers=self.headers
        ).json()
        response = self.client.put(
            f"/api/exceptions/{exceptions[0]['id']}/split",
            headers=self.headers,
            json={"parts": SPLIT_PARTS},
        )
        self.assertEqual(response.status_code, 200, response.text)
        export = self.client.post(
            f"/api/batches/{self.batch_id}/export", headers=self.headers
        ).json()
        self.assertEqual(run_once(self.database_url, self.storage_root), export["id"])
        self.export_id = export["id"]
        with self.app.state.database.session() as session:
            batch = session.get(Batch, self.batch_id)
            target = merged_export_path(batch)
            assert target is not None
            self.target = target
            self.archive = Path(batch.zip_path)
            self.results = [
                Path(source.result_path)
                for source in session.scalars(
                    select(BatchFile)
                    .where(BatchFile.batch_id == self.batch_id)
                    .order_by(BatchFile.file_order)
                )
            ]
        self.target.unlink()
        self.candidate = self.root / "candidate"

    def storage_snapshot(self) -> dict[str, str]:
        return {
            path.relative_to(self.root).as_posix(): sha256(path)
            for path in [self.root / "worker.db", *self.storage_root.rglob("*")]
            if path.is_file()
        }

    def use_legacy_layout(self) -> None:
        for path in self.results:
            book = load_workbook(BytesIO(path.read_bytes()))
            book["交货导入"].delete_rows(3)
            book.save(path)
            book.close()
        self.rebuild_archive()

    def rebuild_archive(self) -> None:
        with ZipFile(self.archive, "w") as archive:
            for path in self.results:
                archive.write(path, arcname=path.name)
