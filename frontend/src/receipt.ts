import type { Batch } from "./types";

export function receiptReady(batch: Batch) {
  return (
    batch.workflow !== "self_operated_inbound" || (batch.receipt?.requested_total != null && !batch.receipt.issue_count)
  );
}

export function receiptInputBusy(batch: Batch) {
  return (
    ["queued", "running"].includes(batch.status) ||
    Object.values(batch.jobs ?? {}).some((job) => ["queued", "running"].includes(job.status))
  );
}

export function receiptSiteDisabledReason(batch: Batch) {
  if (receiptInputBusy(batch)) return "后台任务进行中，请完成后再修改输入";
  if (batch.status === "succeeded") return batch.manual_allowance_disabled_reason ?? null;
  return ["draft", "preflight_ready", "failed"].includes(batch.status) ? null : "当前批次状态不可预检";
}
