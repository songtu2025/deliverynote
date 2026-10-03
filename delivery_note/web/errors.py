from collections.abc import Iterator
from contextlib import contextmanager
from typing import NoReturn

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .position_draft_state import (DRAFT_REVISION_CONFLICT_CODE, DraftConflictError)


class CodedHTTPException(HTTPException):
    def __init__(self, *, detail: str, code: str) -> None:
        super().__init__(status_code=409, detail=detail)
        self.code = code


DRAFT_IMPORT_PREVIEW_EXPIRED_CODE = "draft_import_preview_expired"
INPUT_VERSION_NAME_EXISTS_CODE = "input_version_name_exists"


def commit_once(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def rollback_draft_conflict(session: Session, error: DraftConflictError) -> NoReturn:
    if session.in_transaction():
        session.rollback()
    raise CodedHTTPException(
        code=error.code,
        detail=str(error).strip() or "草稿已被其他管理员更新，请刷新后重试",
    ) from error


def rollback_integrity_conflict(session: Session, error: Exception) -> NoReturn:
    if session.in_transaction():
        session.rollback()
    raise CodedHTTPException(
        code=DRAFT_REVISION_CONFLICT_CODE,
        detail="草稿写入发生并发冲突，请刷新后重试",
    ) from error


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CodedHTTPException)
    async def coded_http_exception_handler(
        _request: Request, error: CodedHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail, "code": error.code},
        )


@contextmanager
def commit_draft_changes(session: Session) -> Iterator[None]:
    """统一草稿编辑的单次提交与并发冲突回滚。"""
    try:
        yield
        commit_once(session)
    except DraftConflictError as error:
        rollback_draft_conflict(session, error)
    except IntegrityError as error:
        rollback_integrity_conflict(session, error)
    except ValueError as error:
        if session.in_transaction():
            session.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
