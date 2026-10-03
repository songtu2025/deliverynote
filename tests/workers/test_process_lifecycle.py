from datetime import timedelta
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import MagicMock, patch


import delivery_note.worker as worker_module
import delivery_note.workers.recovery as recovery_module
from delivery_note.web.database import Database


class WorkerProcessLifecycleTests(unittest.TestCase):
    def test_persistent_main_reuses_one_database_and_disposes_it(self):
        class StopAfterOnePoll:
            def __init__(self):
                self.wait_count = 0
                self.stopped = False

            def is_set(self):
                return self.stopped or self.wait_count > 0

            def wait(self, _timeout):
                self.wait_count += 1
                return False

            def set(self):
                self.stopped = True

        database = MagicMock()
        session = database.session.return_value.__enter__.return_value
        session.scalar.return_value = None
        session.scalars.return_value.all.return_value = []
        with (
            patch.object(worker_module, "Database", return_value=database) as factory,
            patch.object(worker_module, "Event", StopAfterOnePoll),
            patch.object(worker_module, "Thread") as thread_factory,
            patch.object(worker_module.signal, "signal", return_value=None),
        ):
            exit_code = worker_module.main(
                [
                    "--database-url",
                    "sqlite+pysqlite:///unused.db",
                    "--poll-interval",
                    "0.01",
                ]
            )

        self.assertEqual(exit_code, 0)
        factory.assert_called_once_with("sqlite+pysqlite:///unused.db")
        database.dispose.assert_called_once_with()
        thread_factory.return_value.start.assert_called_once_with()
        thread_factory.return_value.join.assert_called_once()

    def test_stale_watcher_continues_after_recovering_a_job(self):
        class StopAfterRecovery:
            def __init__(self):
                self.wait_count = 0

            def wait(self, _timeout):
                self.wait_count += 1
                return self.wait_count > 1

        database = MagicMock()
        with patch.object(
            recovery_module,
            "_recover_stale_jobs",
            return_value=1,
            create=True,
        ) as recover:
            recovery_module._watch_stale_jobs(
                database,
                timedelta(minutes=30),
                StopAfterRecovery(),
                "batch",
                3,
            )

        recover.assert_called_once_with(
            database,
            stale_after=timedelta(minutes=30),
            queue="batch",
            max_attempts=3,
        )

    def test_worker_exits_cleanly_on_sigterm(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database_url = f"sqlite+pysqlite:///{root / 'worker.db'}"
            database = Database(database_url)
            database.create_schema()
            database.dispose()
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "delivery_note.worker",
                    "--database-url",
                    database_url,
                    "--storage-root",
                    str(root / "storage"),
                    "--poll-interval",
                    "0.05",
                ],
                cwd=Path(__file__).resolve().parents[2],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                time.sleep(2)
                self.assertIsNone(process.poll(), "Worker 在收到信号前意外退出")
                process.terminate()
                returncode = process.wait(timeout=5)
                stdout, stderr = process.communicate()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

        self.assertEqual(returncode, 0, f"stdout={stdout}\nstderr={stderr}")
