from __future__ import annotations

import argparse
import os
import signal
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread

from .web.database import Database
from .workers.leases import (
    WORKER_QUEUES,
)
from .workers.recovery import _recover_stale_jobs, _watch_stale_jobs
from .workers.recovery import recover_stale_jobs as recover_stale_jobs
from .workers.scheduler import _run_once
from .workers.scheduler import run_once as run_once


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("必须是整数") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="交货处理后台任务 Worker")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "sqlite+pysqlite:///delivery_note.db"),
    )
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(os.getenv("STORAGE_ROOT", "storage")),
    )
    parser.add_argument("--queue", choices=WORKER_QUEUES, default="all")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--stale-minutes", type=int, default=30)
    parser.add_argument(
        "--max-attempts",
        type=_positive_int,
        default=os.getenv("WORKER_MAX_ATTEMPTS", "3"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stop_event = Event()
    previous_handlers = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        database = Database(args.database_url)
        try:
            _recover_stale_jobs(
                database,
                stale_after=timedelta(minutes=args.stale_minutes),
                queue=args.queue,
                max_attempts=args.max_attempts,
            )
            if args.once:
                _run_once(database, args.storage_root, args.queue)
                return 0
            stale_after = timedelta(minutes=args.stale_minutes)
            watcher = Thread(
                target=_watch_stale_jobs,
                args=(
                    database,
                    stale_after,
                    stop_event,
                    args.queue,
                    args.max_attempts,
                ),
                name="delivery-note-stale-job-watcher",
                daemon=True,
            )
            watcher.start()
            try:
                while not stop_event.is_set():
                    if _run_once(database, args.storage_root, args.queue) is None:
                        stop_event.wait(args.poll_interval)
            finally:
                stop_event.set()
                watcher.join()
            return 0
        finally:
            database.dispose()
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
