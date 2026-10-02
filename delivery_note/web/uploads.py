import logging
import os
import re
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

LOGGER = logging.getLogger("delivery_note.web.api")


def _safe_filename(filename: str) -> str:
    safe = Path(filename).name
    safe = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", safe).strip(" .")
    if not safe:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    return safe


def _unlink_after_commit(path: Path) -> None:
    """数据库提交后尽力删除旧文件，不让清理故障改变请求结果。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("数据库已提交，但旧文件清理失败：%s", path, exc_info=True)


async def _save_upload(
    upload: UploadFile,
    destination: Path,
    max_bytes: int,
) -> None:
    await run_in_threadpool(destination.parent.mkdir, parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    bytes_written = 0
    output: BinaryIO | None = None
    try:
        output = await run_in_threadpool(temporary.open, "wb")
        try:
            while chunk := await upload.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"上传文件不能超过 {max_bytes} 字节",
                    )
                await run_in_threadpool(output.write, chunk)
        finally:
            await run_in_threadpool(output.close)
            output = None
        await run_in_threadpool(os.replace, temporary, destination)
    finally:
        if output is not None:
            await run_in_threadpool(output.close)
        await run_in_threadpool(temporary.unlink, missing_ok=True)
        await upload.close()
