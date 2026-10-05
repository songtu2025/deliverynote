from tests.support.web_api import WebApiCase
import asyncio
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, BrokenBarrierError, Lock
from unittest.mock import patch
from unittest import IsolatedAsyncioTestCase

from httpx2 import ASGITransport, AsyncClient

import delivery_note.web.input_version_routes as input_version_routes_module
from tests.asgi_client import SyncASGIClient

from delivery_note.web.api import create_app
from delivery_note.web.uploads import build_upload_parser


class UploadParserTests(IsolatedAsyncioTestCase):
    async def test_parser_preserves_arguments_and_result(self) -> None:
        parser = build_upload_parser(1)
        result = {"rows": 3}

        def parse(path: Path, *, expected: Path) -> dict[str, int]:
            self.assertEqual(path, expected)
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            return result

        path = Path("candidate.xlsx")
        actual = await parser(parse, path, expected=path)
        self.assertIs(actual, result)

    async def test_parser_releases_capacity_after_failure(self) -> None:
        parser = build_upload_parser(1)
        error = ValueError("解析失败")

        def fail() -> None:
            raise error

        with self.assertRaises(ValueError) as caught:
            await parser(fail)
        self.assertIs(caught.exception, error)
        self.assertEqual(await asyncio.wait_for(parser(lambda: 7), timeout=2), 7)


class WebApiTests(WebApiCase):
    def test_upload_parsing_runs_off_loop_and_obeys_concurrency_limit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(
                database_url=f"sqlite+pysqlite:///{root / 'parse-limit.db'}",
                storage_root=root / "storage",
                bootstrap_admin=("admin", "admin-pass"),
                max_concurrent_upload_parses=1,
            )
            client = SyncASGIClient(app)
            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin-pass"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            counter_lock = Lock()
            concurrent_parses = Barrier(2)
            active = 0
            maximum_active = 0
            observed_running_loops = []

            def slow_validation(_kind, _path):
                nonlocal active, maximum_active
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    observed_running_loops.append(False)
                else:
                    observed_running_loops.append(True)
                with counter_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    concurrent_parses.wait(timeout=0.3)
                except BrokenBarrierError:
                    pass
                with counter_lock:
                    active -= 1

            try:
                with patch.object(
                    input_version_routes_module,
                    "_validate_input_version",
                    side_effect=slow_validation,
                ):
                    responses = asyncio.run(self._upload_two_versions(app, headers))
            finally:
                client.close()
                app.state.database.dispose()

        self.assertTrue(
            all(response.status_code == 201 for response in responses),
            [response.text for response in responses],
        )
        self.assertEqual(observed_running_loops, [False, False])
        self.assertEqual(maximum_active, 1)

    async def _upload_two_versions(self, app, headers):
        async def keep_event_loop_awake():
            while True:
                await asyncio.sleep(0.01)

        heartbeat = asyncio.create_task(keep_event_loop_awake())
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as async_client:
            try:
                return await asyncio.gather(
                    *(
                        async_client.post(
                            f"/api/input-versions/{kind}",
                            headers=headers,
                            data={
                                "name": f"{kind}-threaded",
                                "activate": "false",
                            },
                            files={
                                "file": (
                                    f"{kind}.xlsx",
                                    BytesIO(b"content"),
                                )
                            },
                        )
                        for kind in ("purchase", "product")
                    )
                )
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
