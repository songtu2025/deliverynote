from tests.support.web_api import WebApiCase
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy import select

from delivery_note.web.auth import hash_token

from delivery_note.web.models import (
    AuthSession,
    User,
)


class WebApiTests(WebApiCase):
    def test_login_sets_http_only_strict_cookie_and_rejects_bad_credentials(self):
        bad_login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(bad_login.status_code, 401)
        self.assertNotIn("set-cookie", bad_login.headers)

        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        cookie = login.headers["set-cookie"]
        self.assertIn("delivery_note_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIn("expires=", cookie.lower())
        self.assertNotIn("; Secure", cookie)
        cookie_expiry = parsedate_to_datetime(
            next(
                attribute.split("=", 1)[1]
                for attribute in cookie.split("; ")
                if attribute.lower().startswith("expires=")
            )
        )
        response_expiry = datetime.fromisoformat(
            login.json()["expires_at"].replace("Z", "+00:00")
        )
        self.assertLessEqual(
            abs(
                (
                    cookie_expiry.astimezone(timezone.utc)
                    - response_expiry.astimezone(timezone.utc)
                ).total_seconds()
            ),
            1,
        )

    def test_cookie_auth_supports_me_and_business_requests_with_bearer_priority(self):
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["token"]
        cookie_headers = {"Cookie": f"delivery_note_session={token}"}

        me = self.client.get("/api/auth/me", headers=cookie_headers)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["username"], "admin")
        batches = self.client.get("/api/batches", headers=cookie_headers)
        self.assertEqual(batches.status_code, 200, batches.text)

        bearer = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(bearer.status_code, 200, bearer.text)
        rejected = self.client.get(
            "/api/auth/me",
            headers={
                "Authorization": "Bearer invalid-bearer",
                "Cookie": f"delivery_note_session={token}",
            },
        )
        self.assertEqual(rejected.status_code, 401, rejected.text)
        self.assertNotIn("set-cookie", rejected.headers)

    def test_cookie_logout_revokes_session_and_clears_cookie(self) -> None:
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        token = login.json()["token"]
        cookie_headers = {"Cookie": f"delivery_note_session={token}"}

        logout = self.client.post("/api/auth/logout", headers=cookie_headers)
        self.assertEqual(logout.status_code, 204, logout.text)
        self.assertEqual(logout.content, b"")
        expired_cookie = logout.headers["set-cookie"]
        self.assertIn("delivery_note_session=", expired_cookie)
        self.assertIn("Max-Age=0", expired_cookie)
        self.assertIn("HttpOnly", expired_cookie)
        self.assertIn("SameSite=strict", expired_cookie)
        with self.app.state.database.session() as session:
            auth_session = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == hash_token(token))
            )
        self.assertIsNone(auth_session)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=cookie_headers).status_code,
            401,
        )

    def test_logout_revokes_bearer_and_cookie_but_keeps_other_sessions(self) -> None:
        bearer_headers, cookie_session, other_headers = (
            self.login("admin", "admin-pass") for _ in range(3)
        )
        cookie_headers = {
            "Cookie": (
                "delivery_note_session=" + cookie_session["Authorization"].split()[1]
            )
        }
        logout = self.client.post(
            "/api/auth/logout", headers={**bearer_headers, **cookie_headers}
        )
        self.assertEqual(logout.status_code, 204, logout.text)
        self.assertEqual(logout.content, b"")
        self.assertIn("Max-Age=0", logout.headers["set-cookie"])
        for headers in (bearer_headers, cookie_headers):
            with self.subTest(headers=list(headers)):
                self.assertEqual(
                    self.client.get("/api/auth/me", headers=headers).status_code, 401
                )
        self.assertEqual(
            self.client.get("/api/auth/me", headers=other_headers).status_code, 200
        )

    def test_invalid_or_disabled_cookie_session_is_cleared(self):
        invalid = self.client.get(
            "/api/auth/me",
            headers={"Cookie": "delivery_note_session=invalid-token"},
        )
        self.assertEqual(invalid.status_code, 401)
        self.assertIn("Max-Age=0", invalid.headers["set-cookie"])

        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        token = login.json()["token"]
        with self.app.state.database.session() as session:
            session.get(User, 1).active = False
            session.commit()
        disabled = self.client.get(
            "/api/auth/me",
            headers={"Cookie": f"delivery_note_session={token}"},
        )
        self.assertEqual(disabled.status_code, 401)
        self.assertIn("Max-Age=0", disabled.headers["set-cookie"])

    def test_expired_cookie_session_is_cleared(self):
        login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        token = login.json()["token"]
        with self.app.state.database.session() as session:
            auth_session = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == hash_token(token))
            )
            auth_session.expires_at = datetime.utcnow() - timedelta(seconds=1)
            session.commit()

        expired = self.client.get(
            "/api/auth/me",
            headers={"Cookie": f"delivery_note_session={token}"},
        )
        self.assertEqual(expired.status_code, 401)
        self.assertIn("Max-Age=0", expired.headers["set-cookie"])
