"""验证同步候选提交异常时的文件保留与清理边界。"""

from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from delivery_note.web.database import Database
from delivery_note.web.models import (
    AuditLog,
    InputVersion,
    PurchaseSyncJob,
    SelfOperatedInboundSyncJob,
)
from delivery_note.workers import sync_inbound, sync_purchase
from delivery_note.workers.leases import JobContext, _claim_sync_job
from delivery_note.workers.sync_models import SYNC_METADATA, SyncJob, SyncJobModel
from delivery_note.workers.sync_results import (
    SyncCandidate,
    _fail_sync_job,
    _publish_sync_candidate,
)
from tests.support.worker import WorkerCase
from tests import test_purchase_sync as mapping_cases


class SyncFileCleanupTests(WorkerCase):
    def assert_publication_failure(self, kind: str, failure: str) -> None:
        module = sync_purchase if kind == "purchase" else sync_inbound
        model = PurchaseSyncJob if kind == "purchase" else SelfOperatedInboundSyncJob
        execute = (
            sync_purchase._execute_purchase_sync
            if kind == "purchase"
            else sync_inbound._execute_self_operated_inbound_sync
        )
        context, previous = self.claimed_candidate(model)
        database = context.database
        real_commit = Session.commit
        real_session = database.session
        inspection_fails = False
        paths: list[Path] = []

        def commit(session: Session) -> None:
            if failure == "after_commit":
                real_commit(session)
            raise RuntimeError("模拟候选提交异常")

        def publish(
            owned: JobContext,
            job_model: SyncJobModel,
            candidate: SyncCandidate,
            details: dict[str, Any],
        ) -> None:
            nonlocal inspection_fails
            paths.append(candidate.path)
            try:
                # 只在候选登记事务中注入异常，领取和进度更新仍真实执行。
                with patch.object(Session, "commit", autospec=True, side_effect=commit):
                    _publish_sync_candidate(owned, job_model, candidate, details)
            finally:
                inspection_fails = failure == "inspection"

        @contextmanager
        def sessions() -> Iterator[Session]:
            nonlocal inspection_fails
            if inspection_fails:
                inspection_fails = False
                raise RuntimeError("模拟清理查询不可用")
            with real_session() as session:
                yield session

        with (
            patch("delivery_note.gerpgo.GerpgoClient.from_config") as factory,
            patch.dict("os.environ", {"PURCHASE_SYNC_MODE": "full"}),
            patch.object(module, "_publish_sync_candidate", side_effect=publish),
            patch.object(database, "session", side_effect=sessions),
        ):
            client = factory.return_value
            client.base_url = "https://example.test"
            client.app_id = "fixture-app"
            client.list_purchase_orders.return_value = [{"code": "PO-1"}]
            client.purchase_order_detail.return_value = (
                mapping_cases.PurchaseMappingTests.detail()
            )
            client.list_self_operated_inbound_orders.return_value = [
                mapping_cases.SelfOperatedInboundMappingTests.order()
            ]
            with self.assertRaisesRegex(RuntimeError, "模拟候选提交异常"):
                execute(context, self.storage_root)

        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].is_file(), failure != "before_commit")
        _fail_sync_job(
            database, model, context.job_id, context.claim_token, "模拟候选提交异常"
        )
        self.assert_saved_state(
            context, model, paths[0], previous, failure == "after_commit"
        )

    def claimed_candidate(
        self, model: SyncJobModel
    ) -> tuple[JobContext, dict[int, tuple[bool, bytes]]]:
        endpoint = (
            "/api/purchase-sync"
            if model is PurchaseSyncJob
            else "/api/self-operated-inbound-sync"
        )
        with patch.dict(
            "os.environ",
            {
                "GERPGO_API_BASE_URL": "https://example.test",
                "GERPGO_APP_ID": "fixture-app",
                "GERPGO_APP_KEY": "fixture-key",
            },
        ):
            started = self.client.post(endpoint, headers=self.headers)
        self.assertEqual(started.status_code, 201, started.text)
        database: Database = self.app.state.database
        with database.session() as session:
            previous = {
                version.id: (version.active, Path(version.storage_path).read_bytes())
                for version in session.scalars(select(InputVersion))
            }
        claimed = _claim_sync_job(database, model)
        assert claimed is not None
        self.assertEqual(claimed[0], started.json()["id"])
        return JobContext(database, claimed[0], claimed[1], lambda: None), previous

    def assert_saved_state(
        self,
        context: JobContext,
        model: SyncJobModel,
        path: Path,
        previous: dict[int, tuple[bool, bytes]],
        committed: bool,
    ) -> None:
        with context.database.session() as session:
            job = cast(SyncJob, session.get(model, context.job_id))
            self.assertEqual(job.status, "succeeded" if committed else "failed")
            self.assertIsNone(job.claim_token)
            self.assertIsNone(job.active_slot)
            self.assertEqual(job.attempts, 1)
            if committed:
                candidate = session.get(InputVersion, job.candidate_version_id)
                assert candidate is not None
                self.assertEqual(Path(candidate.storage_path), path)
                self.assertFalse(candidate.active)
                downloaded = self.client.get(
                    f"/api/input-versions/{candidate.id}/download", headers=self.headers
                )
                self.assertEqual(downloaded.status_code, 200)
                self.assertEqual(downloaded.content, path.read_bytes())
            else:
                self.assertIsNone(job.candidate_version_id)
            versions = list(session.scalars(select(InputVersion)))
            self.assertEqual(len(versions), len(previous) + int(committed))
            for version in versions:
                if version.id in previous:
                    self.assertEqual(
                        (version.active, Path(version.storage_path).read_bytes()),
                        previous[version.id],
                    )
            action = SYNC_METADATA[model][2]
            for status in ("succeeded", "failed"):
                count = session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.action == f"{action}_{status}",
                        AuditLog.entity_id == str(context.job_id),
                    )
                )
                self.assertEqual(count, int(status == job.status))

    def test_purchase_commit_failure_removes_unregistered_file(self) -> None:
        self.assert_publication_failure("purchase", "before_commit")

    def test_inbound_commit_failure_removes_unregistered_file(self) -> None:
        self.assert_publication_failure("inbound", "before_commit")

    def test_purchase_committed_candidate_survives_error(self) -> None:
        self.assert_publication_failure("purchase", "after_commit")

    def test_inbound_committed_candidate_survives_error(self) -> None:
        self.assert_publication_failure("inbound", "after_commit")

    def test_purchase_uncertain_candidate_is_preserved(self) -> None:
        self.assert_publication_failure("purchase", "inspection")

    def test_inbound_uncertain_candidate_is_preserved(self) -> None:
        self.assert_publication_failure("inbound", "inspection")
