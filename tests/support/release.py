"""发布与版本核验测试共用的命令替身。"""

import hashlib
import io
import json
import tarfile
from typing import BinaryIO, Sequence, cast

from scripts.backup.runtime import BackupError
from scripts.deployment_sources import REVISION_LABEL


SHA = "1" * 40
OLD_SHA = "2" * 40


def container(service: str, image: str = "old-image") -> dict[str, object]:
    return {
        "Id": service + "-id",
        "Image": image,
        "Config": {
            "Image": "web-current",
            "Labels": {
                "org.opencontainers.image.revision": OLD_SHA,
            },
        },
        "State": {"Status": "running"},
        "RestartCount": 0,
    }


class ReleaseRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.current_image = "old-image"
        self.dirty = False
        self.image_revision = SHA
        self.failed_rollback = False
        self.recreated_api = False
        self.replace_api_on_update = False
        self.runtime_files = {
            "delivery_note/probe.py": hashlib.sha256(b"version = 1\n").hexdigest(),
            "requirements.lock": hashlib.sha256(b"").hexdigest(),
        }

    def run(self, arguments: Sequence[str], **kwargs: object) -> str:
        arguments = list(arguments)
        self.commands.append(list(arguments))
        if arguments[0] == "git":
            return self.git_command(arguments, kwargs)
        if arguments[:3] == ["docker", "image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "candidate-image"
                        if arguments[-1] == "candidate"
                        else "old-image",
                        "Config": {
                            "Labels": {
                                REVISION_LABEL: self.image_revision
                                if arguments[-1] in {"candidate", "candidate-image"}
                                else OLD_SHA,
                            }
                        },
                    }
                ]
            )
        if "up" in arguments and self.current_image == "candidate-image":
            self.recreated_api = self.replace_api_on_update
        if "ps" in arguments:
            return arguments[-1] + "-id"
        if arguments[:2] == ["docker", "inspect"]:
            return self.inspect(arguments[2:])
        if arguments[:2] == ["docker", "exec"]:
            return json.dumps({"files": self.runtime_files, "versions": {}})
        if arguments[:3] == ["docker", "image", "tag"]:
            self.tag_image(arguments)
        return ""

    def git_command(self, arguments: list[str], kwargs: dict[str, object]) -> str:
        if "archive" in arguments:
            revision = arguments[arguments.index("archive") + 1]
            with tarfile.open(
                fileobj=cast(BinaryIO, kwargs["stdout"]), mode="w"
            ) as archive:
                for name, content in {
                    "delivery_note/probe.py": b"version = 1\n"
                    if revision == OLD_SHA
                    else b"version = 2\n",
                    "requirements.lock": b"",
                }.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
            return ""
        if "rev-parse" in arguments:
            return SHA
        return " M source.py" if self.dirty else ""

    def tag_image(self, arguments: list[str]) -> None:
        if arguments[3] == "candidate-image":
            self.current_image = "candidate-image"
        elif arguments[-1] == "web-current":
            if self.failed_rollback:
                raise BackupError("恢复镜像失败")
            self.current_image = "old-image"

    def inspect(self, identifiers: Sequence[str]) -> str:
        records = []
        for identifier in identifiers:
            record = container(identifier.removesuffix("-id"))
            if identifier == "web-id":
                record = container("web", self.current_image)
                record["Config"] = {
                    "Image": "web-current",
                    "Labels": {
                        REVISION_LABEL: (
                            SHA if self.current_image == "candidate-image" else OLD_SHA
                        )
                    },
                }
            if identifier == "api-id" and self.recreated_api:
                record["Id"] = "unexpected-api-id"
            records.append(record)
        return json.dumps(records)
