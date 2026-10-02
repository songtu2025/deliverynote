from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import AuthSession, User

ROLES = {"admin", "operator"}


def create_user_account(
    session: Session, username: str, password: str, role: str
) -> User:
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="角色无效")
    if session.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    session.flush()
    return user


def change_user_status(
    session: Session, user_id: int, active: bool, admin_id: int
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin_id and not active:
        raise HTTPException(status_code=409, detail="不能停用当前登录账号")
    user.active = active
    if not active:
        session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    return user


def reset_account_password(session: Session, user_id: int, password: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.password_hash = hash_password(password)
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    return user
