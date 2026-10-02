"""两类同步任务共用的模型类型和审计名称。"""

from ..web.models import PurchaseSyncJob, SelfOperatedInboundSyncJob

SyncJobModel = type[PurchaseSyncJob] | type[SelfOperatedInboundSyncJob]
SyncJob = PurchaseSyncJob | SelfOperatedInboundSyncJob
SYNC_METADATA = {
    PurchaseSyncJob: ("采购同步", "purchase_sync_job", "purchase_sync"),
    SelfOperatedInboundSyncJob: (
        "待入库同步",
        "self_operated_inbound_sync_job",
        "self_operated_inbound_sync",
    ),
}
