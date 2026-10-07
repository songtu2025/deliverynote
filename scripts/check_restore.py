"""只读校验备份完整性和本机恢复镜像，不执行恢复。"""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup.manifest import read_manifest, verify_image  # noqa: E402
from scripts.backup.runtime import BackupError, SubprocessRunner  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-directory", type=Path, required=True)
    parser.add_argument("--image", required=True, help="本机已存在的目标应用镜像")
    arguments = parser.parse_args(argv)
    try:
        manifest = read_manifest(arguments.backup_directory)
        image = verify_image(manifest, SubprocessRunner(), arguments.image)
    except BackupError as error:
        print(f"恢复预检失败：{error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "passed",
                "scope": "backup_and_image",
                "schema_version": 3,
                "application_image": image,
                "resource_records": len(manifest.resources),
                "restore_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
