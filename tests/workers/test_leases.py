from tests.support.worker import WorkerCase
from threading import Event, Thread
import time
from unittest.mock import patch


import delivery_note.workers.scheduler as scheduler_module
import delivery_note.workers.compute_delivery as compute_module
import delivery_note.workers.leases as lease_module
from delivery_note.web.models import (
    Batch,
    Job,
)

from delivery_note.workers.scheduler import _fail_job
from delivery_note.worker import (
    run_once,
)


class WorkerIntegrationTests(WorkerCase):
    def test_background_heartbeat_runs_during_blocking_execution_and_stops(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        _batch_id, job_id = self.create_batch([delivery])
        execution_started = Event()
        release_execution = Event()
        heartbeat_seen = Event()
        original_heartbeat = scheduler_module._heartbeat

        def block_execution(*_args):
            execution_started.set()
            self.assertTrue(release_execution.wait(2))

        def observe_heartbeat(*args):
            original_heartbeat(*args)
            heartbeat_seen.set()

        result = []
        with (
            patch.object(lease_module, "LEASE_HEARTBEAT_INTERVAL_SECONDS", 0.01),
            patch.object(
                scheduler_module,
                "_execute_compute",
                side_effect=block_execution,
            ),
            patch.object(
                scheduler_module,
                "_heartbeat",
                side_effect=observe_heartbeat,
            ) as beat,
        ):
            thread = Thread(
                target=lambda: result.append(
                    run_once(self.database_url, self.storage_root, queue="batch")
                )
            )
            thread.start()
            self.assertTrue(execution_started.wait(2))
            self.assertTrue(heartbeat_seen.wait(2))
            release_execution.set()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            heartbeat_count = beat.call_count
            time.sleep(0.05)
            self.assertEqual(beat.call_count, heartbeat_count)

        self.assertEqual(result, [job_id])

    def test_lost_lease_is_logged_and_cannot_be_overwritten(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        batch_id, job_id = self.create_batch([delivery])
        execution_started = Event()
        release_execution = Event()
        lease_lost = Event()
        original_heartbeat = scheduler_module._heartbeat
        original_process = compute_module.process_delivery_batch

        def block_execution(*args, **kwargs):
            execution_started.set()
            self.assertTrue(release_execution.wait(2))
            return original_process(*args, **kwargs)

        def observe_lease_loss(*args):
            try:
                original_heartbeat(*args)
            except lease_module.LostJobLeaseError:
                lease_lost.set()
                raise

        result = []
        with self.assertLogs("delivery_note.worker", level="ERROR") as logs:
            with (
                patch.object(
                    lease_module,
                    "LEASE_HEARTBEAT_INTERVAL_SECONDS",
                    0.01,
                ),
                patch.object(
                    compute_module,
                    "process_delivery_batch",
                    side_effect=block_execution,
                ),
                patch.object(
                    scheduler_module,
                    "_heartbeat",
                    side_effect=observe_lease_loss,
                ),
            ):
                thread = Thread(
                    target=lambda: result.append(
                        run_once(
                            self.database_url,
                            self.storage_root,
                            queue="batch",
                        )
                    )
                )
                thread.start()
                self.assertTrue(execution_started.wait(2))
                with self.app.state.database.session() as session:
                    job = session.get(Job, job_id)
                    original_claim_prefix = job.claim_token[:8]
                    job.claim_token = "replacement-claim"
                    batch = session.get(Batch, batch_id)
                    batch.status = "running"
                    session.commit()
                self.assertTrue(lease_lost.wait(2))
                release_execution.set()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

        self.assertEqual(result, [job_id])
        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            batch = session.get(Batch, batch_id)
            self.assertEqual(job.status, "running")
            self.assertEqual(job.claim_token, "replacement-claim")
            self.assertEqual(batch.status, "running")
        log_output = "\n".join(logs.output)
        self.assertIn(f"queue=batch job_id={job_id}", log_output)
        self.assertIn(f"claim={original_claim_prefix}", log_output)
        self.assertIn("Traceback", log_output)

    def test_successful_finalize_stops_heartbeat_before_terminal_state(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx",
            20,
        )
        _batch_id, job_id = self.create_batch([delivery])
        heartbeat_after_terminal = Event()
        original_execute = scheduler_module._execute_compute
        original_heartbeat = scheduler_module._heartbeat

        def delay_after_finalize(*args):
            original_execute(*args)
            time.sleep(0.05)

        def observe_heartbeat(database, current_job_id, claim_token):
            with database.session() as session:
                if session.get(Job, current_job_id).status != "running":
                    heartbeat_after_terminal.set()
            original_heartbeat(database, current_job_id, claim_token)

        with (
            patch.object(lease_module, "LEASE_HEARTBEAT_INTERVAL_SECONDS", 0.005),
            patch.object(
                scheduler_module,
                "_execute_compute",
                side_effect=delay_after_finalize,
            ),
            patch.object(
                scheduler_module,
                "_heartbeat",
                side_effect=observe_heartbeat,
            ),
            patch.object(scheduler_module.LOGGER, "exception") as log_failure,
        ):
            completed_id = run_once(
                self.database_url,
                self.storage_root,
                queue="batch",
            )

        self.assertEqual(completed_id, job_id)
        self.assertFalse(heartbeat_after_terminal.is_set())
        log_failure.assert_not_called()
        with self.app.state.database.session() as session:
            self.assertEqual(session.get(Job, job_id).status, "succeeded")

    def test_stale_worker_cannot_overwrite_new_claim(self):
        delivery = self.create_delivery(
            self.root / "260717-狂飙-A交货单-发货10箱.xlsx", 20
        )
        batch_id, job_id = self.create_batch([delivery])
        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            job.status = "running"
            job.claim_token = "new-claim"
            job.error_message = None
            batch = session.get(Batch, batch_id)
            batch.status = "running"
            session.commit()

        _fail_job(self.app.state.database, job_id, "old-claim", "旧 Worker 失败")

        with self.app.state.database.session() as session:
            job = session.get(Job, job_id)
            batch = session.get(Batch, batch_id)
            self.assertEqual(job.status, "running")
            self.assertEqual(job.claim_token, "new-claim")
            self.assertIsNone(job.error_message)
            self.assertEqual(batch.status, "running")
