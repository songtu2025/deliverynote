"""只在隔离测试中阻塞业务调用，仍运行正式 Worker 入口和执行逻辑。"""

from dataclasses import replace
from functools import wraps
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

sys.path.insert(0, str(Path.cwd()))

from delivery_note import worker  # noqa: E402
from delivery_note.workers import scheduler  # noqa: E402


def pause(kind: str, identifier: int, claim: str) -> None:
    control = Path(os.environ["WORKER_TEST_CONTROL"])
    hold = control / (kind + ".hold")
    if not hold.exists():
        return
    marker = control / (kind + ".arrived")
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps({"id": identifier, "claim": claim}))
    temporary.replace(marker)
    deadline = time.monotonic() + 120
    while hold.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("隔离测试阻塞点未放行")
        time.sleep(0.05)


def gated(kind: str, execute: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(execute)
    def call(*args: Any, **kwargs: Any) -> Any:
        context = args[0]
        identifier = args[1] if kind == "compute" else context.job_id
        claim = args[3] if kind == "compute" else context.claim_token
        pause(kind, identifier, claim)
        original = args[4] if kind == "compute" else context.before_finalize

        def finalize() -> None:
            pause(kind + ".finalize", identifier, claim)
            original()

        values = list(args)
        if kind == "compute":
            values[4] = finalize
        else:
            values[0] = replace(context, before_finalize=finalize)
        return execute(*values, **kwargs)

    return call


if __name__ == "__main__":
    for name, kind in (
        ("_execute_compute", "compute"),
        ("_execute_export", "export"),
        ("_execute_purchase_sync", "purchase-sync"),
        ("_execute_self_operated_inbound_sync", "inbound-sync"),
    ):
        setattr(scheduler, name, gated(kind, getattr(scheduler, name)))
    raise SystemExit(worker.main())
