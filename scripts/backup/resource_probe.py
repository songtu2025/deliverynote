"""在实际应用镜像中只读验证资源，标准输出仅包含脱敏证据。"""

import json
import os
from pathlib import Path
import sys

from scripts.backup.archive import sha256
from scripts.backup.resources import ResourceReport
from scripts.backup.runtime import BackupError
from scripts.storage_resources import (
    builtin_paths_from_rows,
    inspect_resource,
    runtime_paths,
)


def inspect_resources(root: Path, references: list[tuple[str, str]]) -> ResourceReport:
    builtin_paths = builtin_paths_from_rows(references)
    for kind, value in references:
        path = Path(value)
        if ".." in path.parts or (
            not path.is_relative_to(root)
            and path not in builtin_paths_from_rows([(kind, value)])
        ):
            raise BackupError("存在无法由文件卷或已登记内置模板恢复的外部引用")
    report: ResourceReport = {}
    for path in sorted(set(runtime_paths(root)) | builtin_paths):
        if path not in builtin_paths and not os.path.lexists(path):
            report[str(path)] = {
                "validation": "absent",
                "recovery_source": "data_volume",
            }
            continue
        result = inspect_resource(path, root, builtin_paths)
        if result is None or result[2]["validation"] != "passed":
            raise BackupError("资源校验失败，请复核配置、缓存来源或内置模板")
        state = path.stat()
        report[str(path)] = {
            **result[2],
            "sha256": result[2].get("sha256") or sha256(path),
            "mode": state.st_mode & 0o777,
            "uid": state.st_uid,
            "gid": state.st_gid,
        }
    return report


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        # 凭据通过标准输入进入进程，不出现在命令行、元数据或失败原因中。
        os.environ.update(payload["environment"])
        report = inspect_resources(Path(payload["root"]), payload["references"])
        print(json.dumps(report, ensure_ascii=False))
    except Exception:
        print("资源校验失败，请复核配置、缓存来源或内置模板", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
