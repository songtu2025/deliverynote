from tests.support.web_api import WebApiCase


class WebApiTests(WebApiCase):
    def test_login_and_admin_role_are_enforced(self):
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

        logout = self.client.post("/api/auth/logout", headers=operator_headers)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=operator_headers).status_code,
            401,
        )

    def test_admin_can_disable_and_reset_operator_password(self):
        admin_headers = self.login("admin", "admin-pass")
        operator = self.create_operator(admin_headers)

        disabled = self.client.put(
            f"/api/users/{operator['id']}/status",
            headers=admin_headers,
            json={"active": False},
        )
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertFalse(disabled.json()["active"])
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
        reset = self.client.put(
            f"/api/users/{operator['id']}/password",
            headers=admin_headers,
            json={"password": "operator-new-pass"},
        )
        self.assertEqual(reset.status_code, 204, reset.text)
        self.assertEqual(
            self.client.post(
                "/api/auth/login",
                json={"username": "operator", "password": "operator-pass"},
            ).status_code,
            401,
        )
        self.login("operator", "operator-new-pass")
