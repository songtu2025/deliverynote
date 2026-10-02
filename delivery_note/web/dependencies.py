from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import SESSION_COOKIE_NAME, _deleted_session_cookie_header, hash_token
from .caches import PositionFrameCache
from .database import Database
from .models import AuthSession, Batch, InputDraft, User
from .position_drafts import POSITION_FRAME_CACHE_SESSION_KEY


class BatchLookup(Protocol):
    def __call__(
        self, batch_id: int, session: Session, *, for_update: bool = False
    ) -> Batch: ...


@dataclass(frozen=True)
class RequestDependencies:
    """路由共用的会话、权限和对象查询依赖。"""

    get_session: Callable[[], Iterator[Session]]
    current_user: Callable[..., User]
    admin_user: Callable[..., User]
    bearer: HTTPBearer
    get_batch_or_404: BatchLookup
    get_draft_or_404: Callable[[int, Session], InputDraft]


def build_request_dependencies(
    database: Database,
    position_frame_cache: PositionFrameCache,
    configured_session_cookie_secure: bool,
) -> RequestDependencies:

    def get_session() -> Iterator[Session]:
        session = database.SessionLocal()
        session.info[POSITION_FRAME_CACHE_SESSION_KEY] = position_frame_cache
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_batch_or_404(
        batch_id: int, session: Session, *, for_update: bool = False
    ) -> Batch:
        batch = (
            session.scalar(
                select(Batch)
                .where(Batch.id == batch_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if for_update
            else session.get(Batch, batch_id)
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        return batch

    def get_draft_or_404(draft_id: int, session: Session) -> InputDraft:
        draft = session.get(InputDraft, draft_id)
        if draft is None or draft.kind != "position":
            raise HTTPException(status_code=404, detail="库位草稿不存在")
        return draft

    current_user, admin_user, bearer = _build_auth_dependencies(
        get_session, configured_session_cookie_secure
    )
    return RequestDependencies(
        get_session,
        current_user,
        admin_user,
        bearer,
        get_batch_or_404,
        get_draft_or_404,
    )


def _build_auth_dependencies(
    get_session: Callable[[], Iterator[Session]],
    configured_session_cookie_secure: bool,
) -> tuple[Callable[..., User], Callable[..., User], HTTPBearer]:
    bearer = HTTPBearer(auto_error=False)

    def current_user(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer),
        ],
        session: Annotated[Session, Depends(get_session)],
    ) -> User:
        cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
        token = credentials.credentials if credentials is not None else cookie_token
        using_cookie = credentials is None and cookie_token is not None
        if token is None:
            raise HTTPException(status_code=401, detail="未登录")
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(token))
        )
        if auth_session is None or auth_session.expires_at <= datetime.utcnow():
            raise HTTPException(
                status_code=401,
                detail="登录已失效",
                headers=(
                    {
                        "Set-Cookie": _deleted_session_cookie_header(
                            secure=configured_session_cookie_secure
                        )
                    }
                    if using_cookie
                    else None
                ),
            )
        user = session.get(User, auth_session.user_id)
        if user is None or not user.active:
            raise HTTPException(
                status_code=401,
                detail="用户不可用",
                headers=(
                    {
                        "Set-Cookie": _deleted_session_cookie_header(
                            secure=configured_session_cookie_secure
                        )
                    }
                    if using_cookie
                    else None
                ),
            )
        return user

    def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user

    return current_user, admin_user, bearer
