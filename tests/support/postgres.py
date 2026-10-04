from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from delivery_note.web.api import create_app
from delivery_note.web.models import (
    Batch,
    BatchFile,
    InputVersion,
    User,
)
from tests.asgi_client import SyncASGIClient


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")


@unittest.skipUnless(
    POSTGRES_TEST_URL,
    "未设置 POSTGRES_TEST_URL，跳过 PostgreSQL 集成测试",
)
class PostgreSQLCase(unittest.TestCase):
    @staticmethod
    def create_batch(
        session, name: str, username: str = "admin", version_suffix: str = ""
    ):
        user = User(username=username, password_hash="test", role="admin")
        session.add(user)
        session.flush()
        versions = {}
        for kind in ("purchase", "product", "supplier", "position", "template"):
            version = InputVersion(
                kind=kind,
                name=f"{kind}{version_suffix}",
                original_name=f"{kind}.xlsx",
                storage_path=f"/{kind}.xlsx",
                active=True,
                created_by=user.id,
            )
            session.add(version)
            session.flush()
            versions[kind] = version.id
        batch = Batch(
            name=name,
            created_by=user.id,
            purchase_version_id=versions["purchase"],
            product_version_id=versions["product"],
            supplier_version_id=versions["supplier"],
            position_version_id=versions["position"],
            template_version_id=versions["template"],
        )
        session.add(batch)
        session.flush()
        return user, batch, versions

    def setUp(self):
        self.schema = f"test_{uuid4().hex}"
        self.admin_engine = create_engine(POSTGRES_TEST_URL, future=True)
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        parsed_url = make_url(POSTGRES_TEST_URL)
        query = dict(parsed_url.query)
        query["options"] = f"-csearch_path={self.schema}"
        self.database_url = parsed_url.set(query=query).render_as_string(
            hide_password=False
        )

    def tearDown(self):
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin_engine.dispose()

    @contextmanager
    def batch_api(
        self, batch_status: str, file_count: int = 0, preflight_inputs: bool = False
    ):
        with TemporaryDirectory() as directory:
            app = create_app(
                database_url=self.database_url,
                storage_root=Path(directory) / "storage",
                bootstrap_admin=("admin", "admin-pass"),
            )
            client = SyncASGIClient(app)
            try:
                login = client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "admin-pass"},
                )
                self.assertEqual(login.status_code, 200, login.text)
                headers = {"Authorization": f"Bearer {login.json()['token']}"}
                with app.state.database.session() as session:
                    admin = session.query(User).filter_by(username="admin").one()
                    versions = {}
                    version_kinds: tuple[str, ...] = ("product", "supplier")
                    if preflight_inputs:
                        version_kinds += ("purchase", "position", "template")
                    for kind in version_kinds:
                        path = Path(directory) / f"{kind}.xlsx"
                        path.write_bytes(b"test")
                        version = InputVersion(
                            kind=kind,
                            name=f"{kind}-test",
                            original_name=f"{kind}.xlsx",
                            storage_path=str(path),
                            created_by=admin.id,
                        )
                        session.add(version)
                        versions[kind] = version
                    session.flush()
                    batch = Batch(
                        name="concurrency-test",
                        status=batch_status,
                        created_by=admin.id,
                        purchase_version_id=(
                            versions["purchase"].id if preflight_inputs else None
                        ),
                        product_version_id=versions["product"].id,
                        supplier_version_id=versions["supplier"].id,
                        position_version_id=(
                            versions["position"].id if preflight_inputs else None
                        ),
                        template_version_id=(
                            versions["template"].id if preflight_inputs else None
                        ),
                    )
                    session.add(batch)
                    session.flush()
                    file_ids = []
                    for index in range(file_count):
                        path = Path(directory) / f"file-{index}.xlsx"
                        path.write_bytes(b"test")
                        source = BatchFile(
                            batch_id=batch.id,
                            original_name=f"file-{index}.xlsx",
                            storage_path=str(path),
                            file_order=index + 1,
                        )
                        session.add(source)
                        session.flush()
                        file_ids.append(source.id)
                    batch_id = batch.id
                    session.commit()
                yield app, client, headers, batch_id, file_ids
            finally:
                client.close()
                app.state.database.dispose()

    @contextmanager
    def paused_sql(self, engine, prefix: str):
        reached = Event()
        resume = Event()

        def pause(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(prefix):
                reached.set()
                if not resume.wait(timeout=10):
                    raise TimeoutError(f"等待并发 SQL 超时：{prefix}")

        event.listen(engine, "before_cursor_execute", pause)
        try:
            yield reached, resume
        finally:
            resume.set()
            event.remove(engine, "before_cursor_execute", pause)
