"""库位草稿的创建、发布和丢弃事务。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .caches import DraftAnalysis, DraftAnalysisCache
from .errors import (
    CodedHTTPException,
    INPUT_VERSION_NAME_EXISTS_CODE,
    commit_draft_changes,
    commit_once,
    rollback_draft_conflict,
    rollback_integrity_conflict,
)
from .models import InputDraft, InputVersion
from .position_draft_read import draft_json
from .position_draft_state import DraftConflictError, DuplicateInputVersionNameError
from .position_draft_creation import create_or_resume_draft
from .position_drafts import discard_draft, publish_draft
from .position_import_candidates import PositionImportCandidates
from .schemas import DraftMutationPayload, PublishDraftPayload
from .serializers import version_json
from .uploads import _safe_filename


def _locked_position_base(session: Session) -> tuple[InputVersion, bool]:
    list(
        session.scalars(
            select(InputVersion.id)
            .where(InputVersion.kind == "position")
            .order_by(InputVersion.id)
            .with_for_update()
        )
    )
    existing = session.scalar(
        select(InputDraft)
        .where(
            InputDraft.kind == "position",
            InputDraft.status == "editing",
        )
        .with_for_update()
    )
    if existing is not None:
        version = session.get(
            InputVersion,
            existing.base_version_id,
            populate_existing=True,
        )
    else:
        active_version_id = session.scalar(
            select(InputVersion.id).where(
                InputVersion.kind == "position",
                InputVersion.active.is_(True),
            )
        )
        version = (
            session.get(
                InputVersion,
                active_version_id,
                populate_existing=True,
            )
            if active_version_id is not None
            else None
        )
    if version is None:
        raise HTTPException(status_code=404, detail="当前启用的库位版本不存在")
    return version, existing is not None


@dataclass
class PositionDraftLifecycle:
    """共享草稿生命周期所需的文件、缓存和审计资源。"""

    storage: Path
    audit: Callable[..., None]
    analysis_cache: DraftAnalysisCache[DraftAnalysis]
    candidates: PositionImportCandidates

    def create(self, session: Session, user_id: int) -> tuple[dict[str, object], bool]:
        version, resuming = _locked_position_base(session)
        with commit_draft_changes(session):
            draft = create_or_resume_draft(session, version, user_id)
            if resuming:
                self.audit(
                    session,
                    user_id,
                    "resume_input_draft",
                    "input_draft",
                    draft.id,
                    {"base_version_id": draft.base_version_id},
                )
        session.refresh(draft)
        return draft_json(session, draft, self.analysis_cache), resuming

    def publish(
        self,
        session: Session,
        draft: InputDraft,
        payload: PublishDraftPayload,
        user_id: int,
    ) -> dict[str, object]:
        original_name = _safe_filename(f"{payload.name}.xlsx")
        destination = (
            self.storage / "master" / "position" / f"{uuid4().hex}_{original_name}"
        )
        try:
            version = publish_draft(
                session,
                draft,
                payload.revision,
                user_id,
                name=payload.name,
                storage_path=destination,
                confirm_warnings=payload.confirm_warnings,
                original_name=original_name,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        except DuplicateInputVersionNameError as error:
            if session.in_transaction():
                session.rollback()
            raise CodedHTTPException(
                code=INPUT_VERSION_NAME_EXISTS_CODE, detail=str(error)
            ) from error
        except ValueError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error:
            if session.in_transaction():
                session.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"草稿发布失败：{error}",
            ) from error
        session.refresh(version)
        session.refresh(draft)
        self.candidates.remove_draft(draft.id)
        return {
            **version_json(version),
            "draft_revision": draft.revision,
            "draft_status": draft.status,
        }

    def discard(
        self,
        session: Session,
        draft: InputDraft,
        payload: DraftMutationPayload,
        user_id: int,
    ) -> dict[str, object]:
        try:
            discard_draft(
                session,
                draft,
                payload.revision,
                user_id,
            )
            commit_once(session)
        except DraftConflictError as error:
            rollback_draft_conflict(session, error)
        except IntegrityError as error:
            rollback_integrity_conflict(session, error)
        session.refresh(draft)
        self.candidates.remove_draft(draft.id)
        return draft_json(session, draft, self.analysis_cache)
