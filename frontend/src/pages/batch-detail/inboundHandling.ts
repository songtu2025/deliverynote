import type { Batch, BatchFile, DeliveryException } from "../../types";
import type { ManualAllowanceInput } from "../../inboundExceptionApi";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { inboundRowActions } from "./inboundRowActions";

export type HandlingKind = "allowance" | "offline";

export function allowanceDisabledReason(batch: Batch) {
  if (batch.manual_allowance_disabled_reason !== undefined) return batch.manual_allowance_disabled_reason;
  return batch.status !== "succeeded" ? "批次尚未计算成功或当前状态不可重算" : null;
}

export function offlineDisabledReason(batch: Batch, capacity: number) {
  if (["queued", "running"].includes(batch.jobs?.export?.status ?? "")) return "导出任务运行期间不可修改线下处理";
  if (batch.status !== "succeeded") return "批次尚未计算成功";
  return capacity === 0 ? "没有剩余可处理量" : null;
}

export function handlingDisabledReason(batch: Batch, records: DeliveryException[], kind: HandlingKind) {
  if (!records.length) return "请先勾选待处理行";
  for (const record of records) {
    const remaining = remainingTransferQuantity(record);
    if (!inboundRowActions(record.reason, true, { remaining }).includes(kind))
      return `所选行的待处理原因不适用${kind === "allowance" ? "追加超收" : "线下处理"}`;
    const reason = kind === "allowance" ? allowanceDisabledReason(batch) : offlineDisabledReason(batch, remaining);
    if (reason) return reason;
  }
  return null;
}

export function allowanceFor(batch: Batch, supplierCode: string, sku: string, fullSite: string) {
  return batch.manual_allowances?.find(
    (item) => item.supplier_code === supplierCode && item.sku === sku && item.full_site === fullSite
  );
}

export function handlingFormState(batch: Batch, record: DeliveryException, supplier: string, kind: HandlingKind) {
  const remaining = remainingTransferQuantity(record);
  if (kind === "allowance") {
    const existing = allowanceFor(batch, supplier, record.sku, record.full_site);
    return {
      title: "本批追加超收",
      reasonLabel: "原因（选填）",
      quantity: existing?.quantity ?? remaining,
      reason: existing?.reason ?? "",
      existing: Boolean(existing),
      max: undefined,
      disabledReason: allowanceDisabledReason(batch),
      button: "保存并重算"
    };
  }
  const offline = record.offline_quantity ?? 0;
  return {
    title: "线下处理",
    reasonLabel: "备注（选填）",
    quantity: offline || remaining,
    reason: record.offline_note ?? "",
    existing: offline > 0,
    max: remaining + offline,
    disabledReason: offlineDisabledReason(batch, remaining + offline),
    button: "保存线下处理"
  };
}

export function allowanceItems(batch: Batch, records: DeliveryException[], fileById: Record<number, BatchFile>) {
  const grouped = new Map<string, ManualAllowanceInput>();
  for (const record of records) {
    const supplier = fileById[record.batch_file_id]?.supplier_code ?? "";
    const key = JSON.stringify([supplier, record.sku, record.full_site]);
    const existing = allowanceFor(batch, supplier, record.sku, record.full_site);
    const item = grouped.get(key) ?? {
      supplier_code: supplier,
      sku: record.sku,
      full_site: record.full_site,
      quantity: existing?.quantity ?? 0,
      reason: existing?.reason ?? ""
    };
    item.quantity += remainingTransferQuantity(record);
    grouped.set(key, item);
  }
  return [...grouped.values()];
}
