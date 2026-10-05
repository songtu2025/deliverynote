from tests.support.web_api import WebApiCase


class WebApiTests(WebApiCase):
    def test_login_and_admin_role_are_enforced(self) -> None:
        bad_login = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(bad_login.status_code, 401)

        admin_headers = self.login("admin", "admin-pass")
        self.create_operator(admin_headers)
        me = self.client.get("/api/auth/me", headers=admin_headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "admin")

        operator_headers = self.login("operator", "operator-pass")
        forbidden = self.client.post(
            "/api/users",
            headers=operator_headers,
            json={
                "username": "another",
                "password": "another-pass",
                "role": "operator",
            },
        )
        self.assertEqual(forbidden.status_code, 403)
        operations = (
            ("GET", "/api/users", None),
            ("PUT", "/api/users/1/status", {"active": False}),
            ("PUT", "/api/users/1/password", {"password": "another-pass"}),
        )
        for method, path, payload in operations:
            with self.subTest(path=path):
                denied = self.client.request(
                    method, path, headers=operator_headers, json=payload
                )
                self.assertEqual(denied.status_code, 403, denied.text)

        logout = self.client.post("/api/auth/logout", headers=operator_headers)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(logout.content, b"")
        self.assertEqual(
            self.client.get("/api/auth/me", headers=operator_headers).status_code,
            401,
        )

    def test_admin_can_disable_and_reset_operator_password(self) -> None:
        admin_headers = self.login("admin", "admin-pass")
        operator = self.create_operator(admin_headers)
        operator_headers = self.login("operator", "operator-pass")
        cookie_session = self.login("operator", "operator-pass")
        cookie_headers = {
            "Cookie": (
                "delivery_note_session=" + cookie_session["Authorization"].split()[1]
            )
        }

        disabled = self.client.put(
            f"/api/users/{operator['id']}/status",
            headers=admin_headers,
            json={"active": False},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["active"])
        for headers in (operator_headers, cookie_headers):
            self.assertEqual(
                self.client.get("/api/auth/me", headers=headers).status_code, 401
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "operator-pass"},
            ).status_code,
            401,
        )

        self_deactivate = self.client.put(
            "/api/users/1/status",
            headers=admin_headers,
            json={"active": False},
        )
        self.assertEqual(self_deactivate.status_code, 409)

        enabled = self.client.put(
            f"/api/users/{operator['id']}/status",
            headers=admin_headers,
            json={"active": True},
        )
        self.assertTrue(enabled.json()["active"])
        for headers in (operator_headers, cookie_headers):
            self.assertEqual(
                self.client.get("/api/auth/me", headers=headers).status_code, 401
            )
        operator_headers = self.login("operator", "operator-pass")
        cookie_session = self.login("operator", "operator-pass")
        cookie_headers = {
            "Cookie": (
                "delivery_note_session=" + cookie_session["Authorization"].split()[1]
            )
        }
        reset = self.client.put(
            f"/api/users/{operator['id']}/password",
            headers=admin_headers,
            json={"password": "operator-new-pass"},
        )
        self.assertEqual(reset.status_code, 204, reset.text)
        self.assertEqual(reset.content, b"")
        for headers in (operator_headers, cookie_headers):
            self.assertEqual(
                self.client.get("/api/auth/me", headers=headers).status_code, 401
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "operator-pass"},
            ).status_code,
            401,
        )
        self.login("operator", "operator-new-pass")
