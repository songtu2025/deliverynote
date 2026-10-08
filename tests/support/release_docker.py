"""只在独立 Compose 项目内构造代理切换与回退演练环境。"""

import json
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Any, cast
from urllib.error import URLError
from urllib.request import urlopen
import uuid

from scripts.backup.runtime import compose


API_SERVER = """
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def handle_request(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        value = {'method': self.command, 'path': self.path,
                 'body': body.decode(),
                 'authorization': self.headers.get('Authorization')}
        status = 200
        if self.path.startswith('/health'):
            value = {'status': 'ok'}
        elif self.path.startswith('/api/auth/login'):
            status = 401
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())
    do_GET = handle_request
    do_POST = handle_request
    def log_message(self, *args):
        pass
HTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
"""


class ReleaseDockerFixture:
    def __init__(self, image: str, *, verify_sources: bool = False) -> None:
        self.temporary = TemporaryDirectory(prefix="deliverynote-release-test-")
        self.root = Path(self.temporary.name)
        self.project = "deliverynote-release-test-" + uuid.uuid4().hex[:12]
        self.project_name = self.project
        self.images: list[str] = []
        self.replacement = self.project + "-replacement"
        self.compose_file = self.root / "compose.json"
        self.env_file = self.root / ".env"
        self.env_file.write_text("", encoding="utf-8")
        self.parent_image = image
        self.verify_sources = verify_sources
        self.url = ""

    def run(self, *arguments: str) -> str:
        return subprocess.check_output(
            arguments, cwd=self.root, text=True, stderr=subprocess.PIPE, timeout=180
        ).strip()

    def compose(self, *arguments: str) -> str:
        return self.run(*compose(self, *arguments))

    def build_image(self, name: str, revision: str, *, broken: bool = False) -> str:
        tag = self.project + ":" + name
        self.images.append(tag)
        dockerfile = self.root / "Dockerfile"
        source = f"FROM {self.parent_image}\n"
        if broken:
            (self.root / "broken.conf").write_text(
                "server { listen 80; location / { return 503; } }\n", encoding="utf-8"
            )
            source += "COPY broken.conf /etc/nginx/conf.d/default.conf\n"
        dockerfile.write_text(source, encoding="utf-8")
        self.run(
            "docker",
            "build",
            "-q",
            "--label",
            "org.opencontainers.image.revision=" + revision,
            "-t",
            tag,
            str(self.root),
        )
        return tag

    def start(self) -> None:
        self.prepare()
        self.start_services()

    def prepare(self) -> None:
        for arguments in (
            ("init", "--quiet"),
            ("config", "user.name", "Release Test"),
            ("config", "user.email", "release@example.invalid"),
        ):
            self.run("git", *arguments)
        (self.root / ".gitignore").write_text(
            "*\n!.gitignore\n!version.py\n!delivery_note/\n!delivery_note/**\n!requirements.lock\n",
            encoding="utf-8",
        )
        self.prepare_sources()
        version = self.root / "version.py"
        version.write_text("version = 1\n", encoding="utf-8")
        self.run(
            "git",
            "add",
            ".gitignore",
            "version.py",
            "delivery_note",
            "requirements.lock",
        )
        self.run("git", "commit", "--quiet", "-m", "old")
        self.old_revision = self.run("git", "rev-parse", "HEAD")
        version.write_text("version = 2\n", encoding="utf-8")
        self.run("git", "add", "version.py")
        self.run("git", "commit", "--quiet", "-m", "new")
        self.revision = self.run("git", "rev-parse", "HEAD")
        self.current = self.build_image("current", self.old_revision)
        self.candidate = self.build_image("candidate", self.revision)
        backend_image = (
            "python:3.11-slim@sha256:"
            "e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e"
        )
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.compose_file.write_text(
            json.dumps(self._configuration(backend_image, port)), encoding="utf-8"
        )

    def prepare_sources(self) -> None:
        package = self.root / "delivery_note"
        package.mkdir()
        (package / "probe.py").write_text("version = 1\n", encoding="utf-8")
        (self.root / "requirements.lock").write_text("", encoding="utf-8")

    def start_services(self) -> None:
        self.compose("up", "-d", "--wait", "--wait-timeout", "30")
        records = self.inspect("web")
        port = records[0]["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"]
        self.url = "http://127.0.0.1:" + port
        self.wait_ready()

    def _configuration(self, backend_image: str, port: int) -> dict[str, Any]:
        if self.verify_sources:
            # 核验测试使用真实源码文件与提交标签，不依赖无标记的基础镜像。
            backend_tag = self.project + ":backend"
            self.images.append(backend_tag)
            (self.root / "Dockerfile.backend").write_text(
                f"FROM {backend_image}\nWORKDIR /app\n"
                "COPY delivery_note /app/delivery_note\n"
                "COPY requirements.lock /app/requirements.lock\n",
                encoding="utf-8",
            )
            self.run(
                "docker",
                "build",
                "-q",
                "-f",
                str(self.root / "Dockerfile.backend"),
                "--label",
                "org.opencontainers.image.revision=" + self.old_revision,
                "-t",
                backend_tag,
                str(self.root),
            )
            backend_image = backend_tag
        services = {
            "api": {
                "image": backend_image,
                "command": ["python", "-c", API_SERVER],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "python",
                        "-c",
                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready')",
                    ],
                    "interval": "1s",
                    "timeout": "5s",
                    "retries": 30,
                },
            },
            "web": {
                "image": self.current,
                "ports": [f"127.0.0.1:{port}:80"],
                "depends_on": {"api": {"condition": "service_healthy"}},
            },
        }
        for service in ("db", "worker", "purchase-sync-worker", "inbound-sync-worker"):
            services[service] = {
                "image": backend_image,
                "command": ["python", "-c", "import time; time.sleep(600)"],
            }
        return {"services": services}

    def inspect(self, *services: str) -> list[dict[str, Any]]:
        ids = [self.compose("ps", "-q", service) for service in services]
        return cast(
            list[dict[str, Any]], json.loads(self.run("docker", "inspect", *ids))
        )

    def wait_ready(self, seconds: int = 15) -> None:
        deadline = time.monotonic() + seconds
        while True:
            try:
                with urlopen(self.url + "/health/ready", timeout=2) as response:
                    assert json.load(response) == {"status": "ok"}
                return
            except (URLError, ConnectionError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

    def replace_api(self) -> tuple[str, str]:
        record = self.inspect("api")[0]
        network, settings = next(iter(record["NetworkSettings"]["Networks"].items()))
        old_ip = settings["IPAddress"]
        # 旧 API 仍占用原地址时创建替代容器，确保 Docker 分配不同地址。
        self.run(
            "docker",
            "run",
            "-d",
            "--name",
            self.replacement,
            "--network",
            network,
            "--network-alias",
            "api",
            record["Config"]["Image"],
            "python",
            "-c",
            API_SERVER,
        )
        replacement = json.loads(self.run("docker", "inspect", self.replacement))[0]
        new_ip = replacement["NetworkSettings"]["Networks"][network]["IPAddress"]
        assert old_ip != new_ip
        self.run("docker", "rm", "-f", record["Id"])
        return old_ip, new_ip

    def close(self) -> None:
        # 只清理本测试生成的名称，不接触正式项目与数据卷。
        subprocess.run(
            ["docker", "rm", "-f", self.replacement],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if self.compose_file.exists():
            self.compose("down", "--remove-orphans")
        for image in self.images:
            subprocess.run(
                ["docker", "image", "rm", image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        self.temporary.cleanup()
