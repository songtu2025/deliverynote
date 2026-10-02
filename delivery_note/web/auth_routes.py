from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import (
    SESSION_COOKIE_NAME,
    _delete_session_cookie,
    _set_session_cookie,
    hash_token,
    new_session_token,
    verify_password,
)
from .dependencies import RequestDependencies
from .models import AuthSession, User
from .schemas import LoginPayload, PasswordResetPayload, UserPayload, UserStatusPayload
from .serializers import user_json, utc_isoformat
from .user_accounts import (
    change_user_status,
    create_user_account,
    reset_account_password,
)


def register_auth_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    configured_session_cookie_secure: bool,
    _audit: Callable[..., None],
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user
    bearer = dependencies.bearer

    @app.post("/api/auth/login")
    def login(
        payload: LoginPayload,
        response: Response,
        session: Annotated[Session, Depends(get_session)],
    ):
        user = session.scalar(select(User).where(User.username == payload.username))
        if (
            user is None
            or not user.active
            or not verify_password(payload.password, user.password_hash)
        ):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token, token_hash, expires_at = new_session_token()
        session.add(
            AuthSession(
                token_hash=token_hash,
                user_id=user.id,
                expires_at=expires_at,
            )
        )
        _audit(session, user.id, "login", "user", user.id)
        session.commit()
        _set_session_cookie(
            response,
            token,
            expires_at,
            secure=configured_session_cookie_secure,
        )
        return {
            "token": token,
            "expires_at": utc_isoformat(expires_at),
            "user": user_json(user),
        }

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer),
        ],
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        selected_token = (
            credentials.credentials
            if credentials is not None
            else request.cookies.get(SESSION_COOKIE_NAME)
        )
        presented_tokens = {
            token
            for token in (selected_token, request.cookies.get(SESSION_COOKIE_NAME))
            if token
        }
        session.execute(
            delete(AuthSession).where(
                AuthSession.token_hash.in_(
                    hash_token(token) for token in presented_tokens
                )
            )
        )
        _audit(session, user.id, "logout", "user", user.id)
        session.commit()
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        _delete_session_cookie(response, secure=configured_session_cookie_secure)
        return response

    @app.get("/api/auth/me")
    def me(user: Annotated[User, Depends(current_user)]):
        return user_json(user)

    register_user_routes(app, dependencies, _audit)


def register_user_routes(
    app: FastAPI, dependencies: RequestDependencies, _audit: Callable[..., None]
) -> None:
    get_session = dependencies.get_session
    admin_user = dependencies.admin_user

    @app.post("/api/users", status_code=status.HTTP_201_CREATED)
    def create_user(
        payload: UserPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        user = create_user_account(
            session, payload.username, payload.password, payload.role
        )
        _audit(session, admin.id, "create_user", "user", user.id)
        session.commit()
        return user_json(user)

    @app.get("/api/users")
    def list_users(
        _admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        return [
            user_json(user) for user in session.scalars(select(User).order_by(User.id))
        ]

    @app.put("/api/users/{user_id}/status")
    def update_user_status(
        user_id: int,
        payload: UserStatusPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        user = change_user_status(session, user_id, payload.active, admin.id)
        _audit(
            session,
            admin.id,
            "update_user_status",
            "user",
            user.id,
            {"active": payload.active},
        )
        session.commit()
        return user_json(user)

    @app.put(
        "/api/users/{user_id}/password",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def reset_user_password(
        user_id: int,
        payload: PasswordResetPayload,
        admin: Annotated[User, Depends(admin_user)],
        session: Annotated[Session, Depends(get_session)],
    ):
        user = reset_account_password(session, user_id, payload.password)
        _audit(session, admin.id, "reset_user_password", "user", user.id)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
