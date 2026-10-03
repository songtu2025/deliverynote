"""库位草稿的查询、校验和下载入口。"""

from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..inspection.workbooks import write_position_workbook
from .caches import DraftAnalysisCache
from .dependencies import RequestDependencies
from .models import InputDraft, User
from .position_draft_read import (
    draft_analysis,
    draft_json,
    draft_rows_page,
    summarize_issues,
)
from .position_draft_state import list_draft_rows
from .position_draft_state import position_frame
from .schemas import PositionRowFilters


def register_position_draft_read_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    draft_analysis_cache: DraftAnalysisCache,
    storage: Path,
) -> None:
    get_session = dependencies.get_session
    admin_user = dependencies.admin_user
    get_draft_or_404 = dependencies.get_draft_or_404

    @app.get("/api/input-drafts/position")
    def get_position_draft(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = session.scalar(
            select(InputDraft).where(
                InputDraft.kind == "position",
                InputDraft.status == "editing",
            )
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="当前没有进行中的库位草稿")
        return draft_json(session, draft, draft_analysis_cache)

    @app.get("/api/input-drafts/{draft_id}/rows")
    def get_position_draft_rows(
        draft_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
        filters: Annotated[PositionRowFilters, Depends()],
    ):
        draft = get_draft_or_404(draft_id, session)
        return draft_rows_page(session, draft, draft_analysis_cache, filters)

    @app.get("/api/input-drafts/{draft_id}/download")
    def download_position_draft(
        draft_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        download_root = storage / "temporary" / "draft-downloads"
        download_path = download_root / f"{uuid4().hex}.xlsx"
        try:
            write_position_workbook(
                download_path,
                position_frame(list_draft_rows(session, draft.id)),
            )
        except Exception as error:
            download_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail=f"草稿下载文件生成失败：{error}",
            ) from error
        return FileResponse(
            download_path,
            filename=f"position-draft-{draft.id}-r{draft.revision}.xlsx",
            background=BackgroundTask(download_path.unlink, missing_ok=True),
        )

    @app.post("/api/input-drafts/{draft_id}/validate")
    def validate_position_draft(
        draft_id: int,
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        draft = get_draft_or_404(draft_id, session)
        analysis = draft_analysis(session, draft, draft_analysis_cache)
        return {
            "draft_id": draft.id,
            "revision": draft.revision,
            "diff": analysis["diff"],
            **summarize_issues(analysis["issues"]),
        }
