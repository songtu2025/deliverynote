from dataclasses import replace
import io
from unittest.mock import patch
from urllib.error import URLError

from scripts.backup.runtime import BackupError
from scripts.web_verification import resolve_web_url, verify_served_web
from tests.support.backup import BackupTestCase, FakeRunner


class WebVerificationTests(BackupTestCase):
    def test_health_homepage_and_assets_match_running_container(self) -> None:
        runner = FakeRunner()
        verify_served_web(self.config, runner)
        paths = {call.args[0] for call in self.web_requests.call_args_list}
        self.assertEqual(
            paths,
            {
                "http://127.0.0.1:18080/health/live",
                "http://127.0.0.1:18080/health/ready",
                "http://127.0.0.1:18080/",
                "http://127.0.0.1:18080/assets/app.js",
            },
        )
        self.assertEqual(sum("sha256sum" in command for command in runner.commands), 2)

    def test_explicit_url_and_original_web_id_do_not_require_compose_resolution(
        self,
    ) -> None:
        runner = FakeRunner()
        verify_served_web(
            self.config,
            runner,
            web_id="original-web",
            health_url="http://127.0.0.1:19090/",
        )
        self.assertTrue(
            all(command[:2] == ("docker", "exec") for command in runner.commands)
        )
        self.assertTrue(
            all(command[2] == "original-web" for command in runner.commands)
        )

    def test_explicit_url_preserves_existing_cli_configuration(self) -> None:
        runner = FakeRunner()
        self.assertEqual(
            resolve_web_url(
                replace(self.config, health_url="https://example.test/"), runner
            ),
            "https://example.test",
        )
        self.assertEqual(runner.commands, [])

    def test_unavailable_or_ambiguous_port_fails_before_http_requests(self) -> None:
        for address in ("", "127.0.0.1:80\n127.0.0.1:81"):
            with self.subTest(address=address):
                runner = FakeRunner()
                with patch.object(runner, "run", return_value=address):
                    with self.assertRaisesRegex(BackupError, "无法确定 Web 入口"):
                        verify_served_web(self.config, runner)
        self.web_requests.assert_not_called()

    def test_proxy_failure_bad_health_missing_assets_and_stale_content_are_rejected(
        self,
    ) -> None:
        cases = (
            URLError("代理不可用"),
            b'{"status":"failed"}',
            b"<html></html>",
            b'<script src="/assets/app.js"></script>stale',
            b"stale asset",
        )
        for bad in cases:
            with self.subTest(response=bad):

                def response(url: str, *, timeout: int) -> io.BytesIO:
                    if isinstance(bad, URLError):
                        raise bad
                    if bad.startswith(b"{") or "/health/" not in url:
                        if bad == b"stale asset" and not url.endswith("app.js"):
                            return FakeRunner.web_response(url, timeout=timeout)
                        return io.BytesIO(bad)
                    return FakeRunner.web_response(url, timeout=timeout)

                with patch("scripts.web_verification.urlopen", side_effect=response):
                    with patch(
                        "scripts.web_verification.time.monotonic", side_effect=[0, 2]
                    ):
                        with self.assertRaisesRegex(BackupError, "Web 入口验收失败"):
                            verify_served_web(
                                replace(self.config, service_wait_timeout_seconds=1),
                                FakeRunner(),
                            )

    def test_transient_proxy_failure_is_retried(self) -> None:
        runner = FakeRunner()
        original = FakeRunner.web_response
        attempts = 0

        def response(url: str, *, timeout: int) -> io.BytesIO:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise URLError("暂时不可用")
            return original(url, timeout=timeout)

        with patch("scripts.web_verification.urlopen", side_effect=response):
            with patch("scripts.web_verification.time.sleep") as sleep:
                verify_served_web(self.config, runner)
        sleep.assert_called_once_with(1)
