import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Response

_PASSWORD_N = 2**14
_PASSWORD_R = 8
_PASSWORD_P = 1


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_PASSWORD_N,
        r=_PASSWORD_R,
        p=_PASSWORD_P,
    )
    return "scrypt${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_text, digest_text = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_PASSWORD_N,
        r=_PASSWORD_R,
        p=_PASSWORD_P,
    )
    return hmac.compare_digest(actual, expected)


def new_session_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.utcnow() + timedelta(hours=12)
    return token, token_hash, expires_at


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


SESSION_COOKIE_NAME = "delivery_note_session"


def _set_session_cookie(
    response: Response,
    token: str,
    expires_at: datetime,
    *,
    secure: bool,
) -> None:
    """写入与数据库会话同期限的浏览器会话 Cookie。"""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        expires=expires_at.replace(tzinfo=timezone.utc),
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )


def _delete_session_cookie(response: Response, *, secure: bool) -> None:
    """按登录时的属性清除浏览器会话 Cookie。"""
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )


def _deleted_session_cookie_header(*, secure: bool) -> str:
    """生成可附加到鉴权错误响应的 Cookie 清理头。"""
    response = Response()
    _delete_session_cookie(response, secure=secure)
    return response.headers["set-cookie"]
