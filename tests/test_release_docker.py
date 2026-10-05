from dataclasses import replace
import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.support.release_docker import ReleaseDockerFixture


@unittest.skipUnless(
    os.environ.get("RELEASE_DOCKER_TESTS") == "1", "需显式启用隔离 Docker 发布演练"
)
class ReleaseDockerTests(unittest.TestCase):
    def setUp(self) -> None:
        image = os.environ["RELEASE_WEB_IMAGE"]
        self.fixture = ReleaseDockerFixture(image)
        self.addCleanup(self.fixture.close)
        self.fixture.start()

    def test_proxy_recovers_after_api_address_change_without_web_reload(self) -> None:
        fixture = self.fixture
        web_before = fixture.inspect("web")[0]
        old_ip, new_ip = fixture.replace_api()
        self.assertNotEqual(old_ip, new_ip)
        fixture.wait_ready()
        web_after = fixture.inspect("web")[0]
        self.assertEqual(web_before["Id"], web_after["Id"])
        self.assertEqual(
            web_before["State"]["StartedAt"], web_after["State"]["StartedAt"]
        )
        self.assertEqual(web_after["RestartCount"], 0)
        request = Request(
            fixture.url + "/api/echo?value=a%2Fb&order=2",
            data=b'{"value":3}',
            headers={
                "Authorization": "Bearer test-only",
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=5) as response:
            value = json.load(response)
        self.assertEqual(
            value,
            {
                "method": "POST",
                "path": "/api/echo?value=a%2Fb&order=2",
                "body": '{"value":3}',
                "authorization": "Bearer test-only",
            },
        )
        codes = []
        for _ in range(12):
            try:
                urlopen(Request(fixture.url + "/api/auth/login", data=b"{}"), timeout=5)
            except HTTPError as error:
                codes.append(error.code)
                error.close()
        self.assertEqual(codes[0], 401)
        self.assertIn(429, codes)

    def test_failed_web_release_restores_old_image_and_proxy(self) -> None:
        from scripts.backup.runtime import BackupError, SubprocessRunner
        from scripts.release_web import ReleaseConfig, publish_web

        fixture = self.fixture
        before = fixture.inspect(
            "web", "api", "db", "worker", "purchase-sync-worker", "inbound-sync-worker"
        )
        broken = fixture.build_image("broken", fixture.revision, broken=True)
        config = ReleaseConfig(
            root=fixture.root,
            compose_file=fixture.compose_file,
            env_file=fixture.env_file,
            project_name=fixture.project,
            image=broken,
            revision=fixture.revision,
            health_url=fixture.url,
            wait_seconds=3,
            lock_file=fixture.root / "release.lock",
        )
        with self.assertRaisesRegex(BackupError, "已恢复原镜像"):
            publish_web(config, runner=SubprocessRunner())
        fixture.wait_ready()
        after = fixture.inspect(
            "web", "api", "db", "worker", "purchase-sync-worker", "inbound-sync-worker"
        )
        self.assertEqual(before[0]["Image"], after[0]["Image"])
        self.assertEqual(before[0]["Config"]["Image"], after[0]["Config"]["Image"])
        self.assertEqual(
            before[0]["Config"]["Labels"]["org.opencontainers.image.revision"],
            after[0]["Config"]["Labels"]["org.opencontainers.image.revision"],
        )
        for old, restored in zip(before[1:], after[1:]):
            self.assertEqual(old["Id"], restored["Id"])
        self.assertEqual(after[0]["RestartCount"], 0)
        result = publish_web(
            replace(config, image=fixture.candidate), runner=SubprocessRunner()
        )
        self.assertEqual(result["revision"], fixture.revision)
        released = fixture.inspect(
            "web", "api", "db", "worker", "purchase-sync-worker", "inbound-sync-worker"
        )
        self.assertEqual(
            released[0]["Config"]["Labels"]["org.opencontainers.image.revision"],
            fixture.revision,
        )
        for old, updated in zip(before[1:], released[1:]):
            self.assertEqual(old["Id"], updated["Id"])
