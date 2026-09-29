from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Batch, BatchFile, Job, User


def register_batch_export_routes(
    app: FastAPI,
    *,
    get_session: Callable,
    current_user: Callable,
    get_batch_or_404: Callable[[int, Session], Batch],
    merged_export_path: Callable[[Batch], Path | None],
    merged_export_ready: Callable[[Batch, int], bool],
    queue_job: Callable[[Batch, str, User, Session], Job],
    job_json: Callable[[Job], dict],
) -> None:
    @app.post("/api/batches/{batch_id}/export", status_code=status.HTTP_202_ACCEPTED)
    def start_export(
        batch_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = session.scalar(
            select(Batch).where(Batch.id == batch_id).with_for_update()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        if batch.status != "succeeded":
            raise HTTPException(status_code=409, detail="批次尚未计算成功")
        source_count = session.scalar(
            select(func.count())
            .select_from(BatchFile)
            .where(BatchFile.batch_id == batch.id)
        )
        existing = session.scalar(
            select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
        )
        if (
            existing is not None
            and existing.status == "succeeded"
            and source_count > 1
            and not merged_export_ready(batch, source_count)
        ):
            existing.status = "stale"
        try:
            job = queue_job(batch, "export", user, session)
            session.commit()
        except IntegrityError:
            session.rollback()
            job = session.scalar(
                select(Job).where(Job.batch_id == batch.id, Job.kind == "export")
            )
            if job is None:
                raise
        return job_json(job)

    @app.get("/api/batches/{batch_id}/download")
    def download_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        if not batch.zip_path or not Path(batch.zip_path).is_file():
            raise HTTPException(status_code=404, detail="批次导出尚未生成")
        return FileResponse(batch.zip_path, filename=Path(batch.zip_path).name)

    @app.get("/api/batches/{batch_id}/download-merged")
    def download_merged_batch(
        batch_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        batch = get_batch_or_404(batch_id, session)
        source_count = session.scalar(
            select(func.count())
            .select_from(BatchFile)
            .where(BatchFile.batch_id == batch.id)
        )
        merged_path = merged_export_path(batch)
        if source_count <= 1 or merged_path is None or not merged_path.is_file():
            raise HTTPException(status_code=404, detail="批次合并导出尚未生成")
        return FileResponse(merged_path, filename=merged_path.name)

    @app.get("/api/batch-files/{file_id}/download")
    def download_batch_file(
        file_id: int,
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        source = session.get(BatchFile, file_id)
        if (
            source is None
            or not source.result_path
            or not Path(source.result_path).is_file()
        ):
            raise HTTPException(status_code=404, detail="来源文件导出尚未生成")
        return FileResponse(source.result_path, filename=Path(source.result_path).name)
