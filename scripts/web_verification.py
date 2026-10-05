"""发布与备份共用的 Web 入口和运行容器资源验收。"""

import hashlib
import json
import re
import time
from typing import Protocol
from urllib.error import URLError
from urllib.request import urlopen

from scripts.backup.runtime import BackupError, ComposeConfig, Runner, compose


class WebVerificationConfig(ComposeConfig, Protocol):
    @property
    def health_url(self) -> str | None: ...

    @property
    def wait_seconds(self) -> int: ...


def resolve_web_url(config: WebVerificationConfig, runner: Runner) -> str:
    if config.health_url:
        return config.health_url.rstrip("/")
    address = runner.run(compose(config, "port", "web", "80")).strip()
    if len(address.splitlines()) != 1 or ":" not in address:
        raise BackupError("无法确定 Web 入口，请通过 --health-url 指定")
    host, port = address.rsplit(":", 1)
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _verify_response(base: str, runner: Runner, web_id: str) -> None:
    for endpoint in ("live", "ready"):
        with urlopen(base + "/health/" + endpoint, timeout=5) as response:
            if json.load(response) != {"status": "ok"}:
                raise BackupError("Web 代理健康响应不正确")
    with urlopen(base + "/", timeout=5) as response:
        html = response.read()
    assets = set(re.findall(r'(?:src|href)="(/assets/[^"\s]+)"', html.decode()))
    if not assets:
        raise BackupError("正式首页缺少构建资源")
    contents = {"/index.html": html}
    for asset in assets:
        with urlopen(base + asset, timeout=5) as response:
            contents[asset] = response.read()
    for path, content in contents.items():
        digest = runner.run(
            ["docker", "exec", web_id, "sha256sum", "/usr/share/nginx/html" + path]
        ).split()[0]
        if hashlib.sha256(content).hexdigest() != digest:
            raise BackupError(f"对外资源与运行镜像不一致：{path}")


def verify_served_web(
    config: WebVerificationConfig,
    runner: Runner,
    *,
    web_id: str | None = None,
    health_url: str | None = None,
) -> None:
    base = (health_url or resolve_web_url(config, runner)).rstrip("/")
    web_id = web_id or runner.run(compose(config, "ps", "--quiet", "web")).strip()
    deadline = time.monotonic() + config.wait_seconds
    while True:
        try:
            _verify_response(base, runner, web_id)
            return
        except (
            URLError,
            ConnectionError,
            TimeoutError,
            ValueError,
            BackupError,
        ) as error:
            if time.monotonic() >= deadline:
                raise BackupError(f"Web 入口验收失败：{error}") from error
            time.sleep(1)
