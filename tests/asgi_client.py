import asyncio
from contextlib import suppress

from httpx2 import ASGITransport, AsyncClient, Response


async def _keep_event_loop_awake() -> None:
    """避免受影响的主机在线程间唤醒时丢失信号。"""
    while True:
        await asyncio.sleep(0.01)


class SyncASGIClient:
    """为进程内异步传输提供轻量同步封装。"""

    def __init__(self, app):
        self.app = app

    def request(self, method: str, url: str, **kwargs) -> Response:
        async def send() -> Response:
            heartbeat = asyncio.create_task(_keep_event_loop_awake())
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=self.app),
                    base_url="http://testserver",
                ) as client:
                    return await client.request(method, url, **kwargs)
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat

        return asyncio.run(send())

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> Response:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        pass
