import os
from pathlib import Path
from typing import TypedDict

from sqlalchemy import event, select
from sqlalchemy.orm import Session, SessionTransaction

from .models import InputDraft, InputVersion
from .position_draft_state import (
    _PENDING_PUBLISH_KEY,
    DuplicateInputVersionNameError,
    validate_draft,
)


class PendingPublishState(TypedDict):
    """外层事务提交与回滚共用的文件提升状态。"""

    temporary_path: str
    target_path: str
    promoted: bool
    root_commit_started: bool
    root_commit_succeeded: bool


def _remove_pending_publish_files(
    state: PendingPublishState, *, remove_target: bool
) -> None:
    Path(state["temporary_path"]).unlink(missing_ok=True)
    if remove_target and state.get("promoted"):
        Path(state["target_path"]).unlink(missing_ok=True)


@event.listens_for(Session, "before_commit")
def _promote_pending_publish_file(session: Session) -> None:
    state: PendingPublishState | None = session.info.get(_PENDING_PUBLISH_KEY)
    if state is None or session.in_nested_transaction():
        return
    state["root_commit_started"] = True
    target_path = Path(state["target_path"])
    if target_path.exists() or target_path.is_symlink():
        raise ValueError("发布目标文件已存在")
    os.link(state["temporary_path"], target_path)
    state["promoted"] = True
    Path(state["temporary_path"]).unlink()


@event.listens_for(Session, "after_commit")
def _mark_root_publish_commit_succeeded(session: Session) -> None:
    state: PendingPublishState | None = session.info.get(_PENDING_PUBLISH_KEY)
    if (
        state is not None
        and state.get("root_commit_started")
        and not session.in_nested_transaction()
    ):
        state["root_commit_succeeded"] = True


@event.listens_for(Session, "after_transaction_end")
def _finish_pending_publish_file(
    session: Session, transaction: SessionTransaction
) -> None:
    if transaction.parent is not None:
        return
    state: PendingPublishState | None = session.info.pop(_PENDING_PUBLISH_KEY, None)
    if state is not None:
        _remove_pending_publish_files(
            state,
            remove_target=not state.get("root_commit_succeeded", False),
        )


def stage_publication_files(
    session: Session, temporary_path: Path, target_path: Path
) -> None:
    """将文件登记到外层事务，由提交与回滚事件完成清理。"""
    state: PendingPublishState = {
        "temporary_path": str(temporary_path),
        "target_path": str(target_path),
        "promoted": False,
        "root_commit_started": False,
        "root_commit_succeeded": False,
    }
    session.info[_PENDING_PUBLISH_KEY] = state


def validate_publication_target(
    session: Session,
    draft: InputDraft,
    name: str,
    storage_path: Path,
    confirm_warnings: bool,
) -> Path:
    """核对草稿问题、版本名称和正式文件目标。"""
    issues = validate_draft(session, draft)
    if any(issue["severity"] == "error" for issue in issues):
        raise ValueError("草稿仍有错误，不能发布")
    if not confirm_warnings and any(issue["severity"] == "warning" for issue in issues):
        raise ValueError("草稿仍有警告，请确认警告后发布")
    if (
        session.scalar(
            select(InputVersion.id).where(
                InputVersion.kind == "position",
                InputVersion.name == name,
            )
        )
        is not None
    ):
        raise DuplicateInputVersionNameError("版本名称已存在")

    path = Path(storage_path)
    resolved_path = path.resolve()
    registered_paths = {
        Path(registered_path).resolve()
        for registered_path in session.scalars(select(InputVersion.storage_path))
    }
    if resolved_path in registered_paths:
        raise ValueError("发布目标不能使用已注册的正式版本文件")
    if path.exists() or path.is_symlink():
        raise ValueError("发布目标文件已存在")
    if session.info.get(_PENDING_PUBLISH_KEY) is not None:
        raise ValueError("当前事务已有待提交的发布文件")

    return path
