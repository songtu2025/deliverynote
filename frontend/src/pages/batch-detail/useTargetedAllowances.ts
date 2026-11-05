import { useState } from "react";
import type { InboundAllocation, InboundAllocations, ManualAllowanceInput } from "../../inboundExceptionApi";
import type { DeliveryException } from "../../types";
import { useSaveInboundAdjustments } from "./useSaveInboundAdjustments";

function targetKey(row: InboundAllocation) {
  return JSON.stringify([row.inbound_no?.trim().toUpperCase(), row.po_code?.trim().toUpperCase()]);
}

function changedAllowances(
  rows: InboundAllocation[],
  draft: {
    valueFor: (row: InboundAllocation) => number;
    reason: string;
    reasonEdited: boolean;
  },
  identity: Pick<ManualAllowanceInput, "supplier_code" | "sku" | "full_site" | "file_id">
) {
  const changes: ManualAllowanceInput[] = [];
  for (const row of rows) {
    if (!row.inbound_no || !row.po_code) continue;
    const quantity = draft.valueFor(row);
    const changedReason = draft.reasonEdited && quantity > 0 && draft.reason !== (row.extra_reason ?? "");
    if (quantity === (row.extra_quantity ?? 0) && !changedReason) continue;
    changes.push({ ...identity, inbound_no: row.inbound_no, po_code: row.po_code, quantity, reason: draft.reason });
  }
  return changes;
}

export function useTargetedAllowances(
  data: InboundAllocations,
  exception: DeliveryException,
  onSaved?: () => Promise<unknown>
) {
  const rows = [...new Map(data.items.map((row) => [targetKey(row), row])).values()];
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [reasonDraft, setReason] = useState<string | null>(null);
  const reason = reasonDraft ?? rows.find((row) => row.extra_quantity)?.extra_reason ?? "";
  const { busy, save } = useSaveInboundAdjustments(data.batch_id, onSaved);
  const valueFor = (row: InboundAllocation) => quantities[targetKey(row)] ?? row.extra_quantity ?? 0;
  const inactiveTotal = (data.inactive_allowances ?? [])
    .filter((entry) => entry.full_site === exception.full_site)
    .reduce((total, entry) => total + entry.quantity, 0);
  const total = rows.reduce((sum, row) => sum + valueFor(row), inactiveTotal);
  const limit = data.allowance_limit ?? 0;
  const error = total > limit ? "合计追加不得超过 " + limit + "（当前剩余待处理量加已保存的指定追加量）" : null;
  const disabledReason = data.recompute_disabled_reason ?? (!data.batch_id ? "批次尚未计算成功" : null);
  const changes = changedAllowances(
    rows,
    { valueFor, reason: reason.trim(), reasonEdited: reasonDraft !== null },
    {
      supplier_code: data.supplier_code ?? "",
      sku: exception.sku,
      full_site: exception.full_site,
      file_id: exception.batch_file_id
    }
  );
  const submit = async () => {
    if (disabledReason || error || !changes.length) return;
    await save({ allowances: changes, sites: [] });
  };
  return {
    busy,
    disabledReason,
    total,
    limit,
    error,
    reason,
    setReason,
    valueFor,
    submit,
    changed: changes.length > 0,
    setQuantity: (row: InboundAllocation, quantity: number | null) =>
      setQuantities((current) => ({ ...current, [targetKey(row)]: quantity ?? 0 }))
  };
}
