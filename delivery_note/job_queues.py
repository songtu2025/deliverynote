"""批次任务的队列归属，由领取、恢复和排队提示共用。"""

BATCH_JOB_KINDS = ("prepare", "compute", "export")
PURCHASE_SNAPSHOT_KIND = "purchase_snapshot"


def queue_job_kinds(queue: str) -> tuple[str, ...]:
    if queue == "all":
        return (*BATCH_JOB_KINDS, PURCHASE_SNAPSHOT_KIND)
    if queue == "batch":
        return BATCH_JOB_KINDS
    if queue == "purchase-sync":
        return (PURCHASE_SNAPSHOT_KIND,)
    return ()
