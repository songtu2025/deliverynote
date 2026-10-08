"""为后端发布演练提供真实源码提交和独立镜像标签。"""

import json
from pathlib import Path
import shutil

from scripts.backend_release import BackendReleaseConfig
from scripts.deployment_sources import BACKEND_SERVICES
from tests.support.worker_docker import WorkerDockerFixture


class BackendDockerFixture(WorkerDockerFixture):
    def prepare_sources(self) -> None:
        source = Path(__file__).resolve().parents[2]
        shutil.copytree(
            source / "delivery_note",
            self.root / "delivery_note",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copyfile(source / "requirements.lock", self.root / "requirements.lock")

    def backend_image(
        self, name: str, revision: str, *, broken_api: bool = False
    ) -> str:
        tag = self.project + ":" + name
        self.images.append(tag)
        source = f"FROM {self.api_image}\n"
        if broken_api:
            (self.root / "fail-api.py").write_text(
                "import os\nimport sys\n"
                "if sys.argv[1] == 'uvicorn':\n"
                "    raise RuntimeError('模拟候选 API 启动失败')\n"
                "os.execvp(sys.argv[1], sys.argv[1:])\n",
                encoding="utf-8",
            )
            source += (
                "COPY fail-api.py /tmp/fail-api.py\n"
                'ENTRYPOINT ["python", "/tmp/fail-api.py"]\n'
            )
        dockerfile = self.root / "Dockerfile.backend"
        dockerfile.write_text(source, encoding="utf-8")
        self.run(
            "docker",
            "build",
            "-q",
            "-f",
            str(dockerfile),
            "--label",
            "org.opencontainers.image.revision=" + revision,
            "-t",
            tag,
            str(self.root),
        )
        return tag

    def prepare(self) -> None:
        super().prepare()
        original = self.backend_image("backend-old", self.old_revision)
        self.backend_candidate = self.backend_image("backend-candidate", self.revision)
        document = json.loads(self.compose_file.read_text())
        for name in BACKEND_SERVICES:
            tag = self.project + ":" + name
            self.images.append(tag)
            self.run("docker", "image", "tag", original, tag)
            document["services"][name]["image"] = tag
        self.compose_file.write_text(json.dumps(document))

    def release_config(
        self, services: tuple[str, ...] = ("worker",)
    ) -> BackendReleaseConfig:
        return BackendReleaseConfig(
            root=self.root,
            compose_file=self.compose_file,
            env_file=self.env_file,
            project_name=self.project,
            image=self.backend_candidate,
            revision=self.revision,
            health_url=self.url,
            services=services,
            wait_seconds=30,
            stop_timeout_seconds=10,
            job_drain_timeout_seconds=60,
            job_poll_seconds=1,
            lock_file=self.root / "backend-release.lock",
            retained={
                name: self.old_revision
                for name in (BACKEND_SERVICES - set(services)) | {"web"}
            },
        )

    def disable_automatic_migration(self) -> None:
        document = json.loads(self.compose_file.read_text())
        document["services"]["api"]["environment"]["AUTO_MIGRATE_SCHEMA"] = "false"
        self.compose_file.write_text(json.dumps(document))
