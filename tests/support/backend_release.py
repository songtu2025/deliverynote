"""复用发布替身，模拟后端选择性更新和维护恢复。"""

import hashlib
import json
from typing import Sequence

from scripts.backup.runtime import BackupError
from scripts.deployment_sources import BACKEND_SERVICES, RUNTIME_PROBE
from tests.support.release import SHA, OLD_SHA, ReleaseRunner


class BackendRunner(ReleaseRunner):
    def __init__(self) -> None:
        super().__init__()
        self.images = {name: "old-image" for name in (*BACKEND_SERVICES, "web", "db")}
        self.tags = {name + "-current": "old-image" for name in self.images}
        self.running = {name: True for name in self.images}
        self.counts = [0]
        self.failed_service = ""
        self.tampered_candidate = False
        self.automatic_migration = "false"
        self.target_files = {
            **self.runtime_files,
            "delivery_note/probe.py": hashlib.sha256(b"version = 2\n").hexdigest(),
        }

    def run(self, arguments: Sequence[str], **kwargs: object) -> str:
        args = list(arguments)
        if args[0] == "git" or args[:3] == ["docker", "image", "inspect"]:
            return super().run(args, **kwargs)
        self.commands.append(args)
        if args[:2] == ["docker", "compose"]:
            return self.compose_command(args)
        return self.docker_command(args)

    def compose_command(self, args: list[str]) -> str:
        if "config" in args and "--format" in args:
            return json.dumps(
                {
                    "services": {
                        "api": {
                            "environment": {
                                "AUTO_MIGRATE_SCHEMA": self.automatic_migration,
                            }
                        }
                    }
                }
            )
        if "stop" in args:
            for name in set(args) & self.running.keys():
                self.running[name] = False
        elif "up" in args:
            self.update(args[-1])
        elif "ps" in args:
            if "--services" in args:
                return "\n".join(name for name in self.running if self.running[name])
            return args[-1] + "-id"
        elif "psql" in args:
            count = self.counts[0]
            if len(self.counts) > 1:
                self.counts.pop(0)
            return str(count)
        return ""

    def docker_command(self, args: list[str]) -> str:
        if args[:3] == ["docker", "image", "tag"]:
            if (
                self.failed_rollback
                and args[3] == "old-image"
                and args[-1].endswith("-current")
            ):
                raise BackupError("模拟镜像回退失败")
            self.tags[args[-1]] = args[3]
        elif args[:2] == ["docker", "start"]:
            for name in self.running:
                if name + "-id" in args:
                    self.running[name] = True
        elif args[:2] == ["docker", "inspect"]:
            return self.inspect(args[2:])
        elif args[:2] == ["docker", "run"]:
            files = self.runtime_files if self.tampered_candidate else self.target_files
            return json.dumps({"files": files, "versions": {}})
        elif args[:2] == ["docker", "exec"] and args[-1] == RUNTIME_PROBE:
            name = args[2].removesuffix("-id")
            files = (
                self.target_files
                if self.images[name] == "candidate-image"
                else self.runtime_files
            )
            return json.dumps({"files": files, "versions": {}})
        return ""

    def update(self, name: str) -> None:
        self.images[name] = self.tags[name + "-current"]
        if name == self.failed_service and self.images[name] == "candidate-image":
            raise BackupError("模拟候选服务启动失败")
        self.running[name] = True

    def inspect(self, identifiers: Sequence[str]) -> str:
        records = []
        for identifier in identifiers:
            name = identifier.removesuffix("-id")
            records.append(
                {
                    "Id": identifier,
                    "Image": self.images[name],
                    "Config": {
                        "Image": name + "-current",
                        "Labels": {
                            "org.opencontainers.image.revision": SHA
                            if self.images[name] == "candidate-image"
                            else OLD_SHA,
                        },
                    },
                    "State": {"Status": "running" if self.running[name] else "exited"},
                    "RestartCount": 0,
                    "Mounts": [],
                }
            )
        return json.dumps(records)
