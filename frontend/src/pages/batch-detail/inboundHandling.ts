import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";

export type AllowanceRecord = Pick<DeliveryException, "sku" | "full_site">;

export function allowanceKey(supplier: string, record: AllowanceRecord) {
  return JSON.stringify([supplier, record.sku, record.full_site]);
}

export function allowanceDisabledReason(batch: Batch) {
  if (batch.manual_allowance_disabled_reason !== undefined) return batch.manual_allowance_disabled_reason;
  return batch.status !== "succeeded" ? "批次尚未计算成功或当前状态不可重算" : null;
}

function offlineDisabledReason(batch: Batch, capacity: number) {
  if (["queued", "running"].includes(batch.jobs?.export?.status ?? "")) return "导出任务运行期间不可修改线下处理";
  if (batch.status !== "succeeded") return "批次尚未计算成功";
  return capacity <= 0 ? "没有剩余可处理量" : null;
}

export function offlineSelectionDisabledReason(batch: Batch, records: DeliveryException[]) {
  if (!records.length) return "请先勾选待处理行";
  for (const record of records) {
    const reason = offlineDisabledReason(batch, remainingTransferQuantity(record));
    if (reason) return reason;
  }
  return null;
}
