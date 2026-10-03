from tests.support.worker import WorkerCase


import delivery_note.workers.export_files as export_files_module
from delivery_note.web.models import (
    Batch,
)


class WorkerIntegrationTests(WorkerCase):
    def test_previous_export_cleanup_has_strict_directory_boundary(self):
        export_root = self.storage_root / "batches" / "123" / "exports"
        current_dir = export_root / "export-current"
        old_dir = export_root / "export-old"
        referenced_dir = export_root / "export-referenced"
        non_export_dir = export_root / "keep-old"
        nested_dir = export_root / "nested" / "export-nested"
        outside_dir = self.storage_root / "export-outside"
        directories = [
            current_dir,
            old_dir,
            referenced_dir,
            non_export_dir,
            nested_dir,
            outside_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True)
            (directory / "artifact.xlsx").write_bytes(b"test")
        created = self.client.post(
            "/api/batches",
            headers=self.headers,
            json={"name": "旧导出目录引用保护"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        with self.app.state.database.session() as session:
            batch = session.get(Batch, created.json()["id"])
            batch.zip_path = str(referenced_dir / "artifact.xlsx")
            session.commit()

        export_files_module._cleanup_previous_export_directories(
            self.app.state.database,
            export_root,
            current_dir,
            [directory / "artifact.xlsx" for directory in directories],
        )

        self.assertFalse(old_dir.exists())
        self.assertTrue(current_dir.is_dir())
        self.assertTrue(referenced_dir.is_dir())
        self.assertTrue(non_export_dir.is_dir())
        self.assertTrue(nested_dir.is_dir())
        self.assertTrue(outside_dir.is_dir())
