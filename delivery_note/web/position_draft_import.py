"""库位草稿导入文件的预览和应用事务。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..excel_io import read_position_workbook
from ..input_inspection import (
    position_change_warnings,
    position_diff,
    validate_position_frame,
)
from .errors import commit_once, rollback_draft_conflict, rollback_integrity_conflict
from .models import InputDraft
from .position_draft_read import summarize_issues
from .position_draft_state import DraftConflictError, require_revision, position_frame
from .position_draft_state import list_draft_rows
from .position_draft_replacement import replace_draft_from_frame
from .position_import_candidates import PositionImportCandidates
from .schemas import ImportApplyPayload, PositionImportForm
from .uploads import _safe_filename, _save_upload


def _inspect_position_import(
    path: Path,
    current_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list, dict]:
    """在线程池中读取并检查库位导入文件。"""
    candidate_frame = read_position_workbook(path)
    issues = [
        *validate_position_frame(candidate_frame),
        *position_change_warnings(current_frame, candidate_frame),
    ]
    return candidate_frame, issues, position_diff(current_frame, candidate_frame)


@dataclass
class PositionDraftImporter:
    """保持运行时上传限制与预览有效期的同一读取来源。"""

    app: FastAPI
    candidates: PositionImportCandidates
    parse_workbook: Callable[..., Awaitable[Any]]

    async def preview(
        self,
        session: Session,
        draft: InputDraft,
        form: PositionImportForm,
        user_id: int,
    ) -> dict:
        try:
            require_revision(draft, form.revision)
        except DraftConflictError as error:
            await form.file.close()
            rollback_draft_conflict(session, error)
        original_name = _safe_filename(form.file.filename or "")
        if Path(original_name).suffix.lower() not in {".xls", ".xlsx"}:
            await form.file.close()
            raise HTTPException(status_code=400, detail="仅支持 Excel 文件")
        token = uuid4().hex
        suffix = Path(original_name).suffix.lower()
        destination = (
            self.candidates.root / f"{draft.id}_{form.revision}_{token}{suffix}"
        )
        await _save_upload(form.file, destination, self.app.state.max_upload_bytes)
        try:
            current_frame = position_frame(list_draft_rows(session, draft.id))
            candidate_frame, issues, diff = await self.parse_workbook(
                _inspect_position_import,
                destination,
                current_frame,
            )
        except Exception as error:
            await run_in_threadpool(destination.unlink, missing_ok=True)
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"导入文件校验失败：{error}",
            ) from error
        await run_in_threadpool(self.candidates.remove_draft, draft.id)
        await run_in_threadpool(
            self.candidates.register,
            token,
            {
                "draft_id": draft.id,
                "revision": form.revision,
                "path": str(destination),
                "created_by": user_id,
                "expires_at": datetime.utcnow()
                + timedelta(seconds=self.app.state.import_candidate_ttl_seconds),
            },
        )
        return {
            "token": token,
            "draft_id": draft.id,
            "revision": form.revision,
            "row_count": len(candidate_frame),
            "diff": diff,
            **summarize_issues(issues),
        }

    def apply(
        self,
        session: Session,
        draft: InputDraft,
        payload: ImportApplyPayload,
        user_id: int,
    ) -> dict:
        candidate_path = self.candidates.consume(session, draft, payload, user_id)
        try:
            candidate_frame = read_position_workbook(candidate_path)
            diff = replace_draft_from_frame(
                session,
                draft,
                payload.revision,
                user_id,
                candidate_frame,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except Exception as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"导入草稿失败：{error}",
            ) from error
        finally:
            candidate_path.unlink(missing_ok=True)
        session.refresh(draft)
        self.candidates.remove_draft(draft.id)
        return {"diff": diff, "revision": draft.revision}
