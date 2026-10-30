import { api, ApiError } from "./api";
import type { Job } from "./types";

export type PurchaseOption = {
  id: string;
  po_code: string;
  site: string;
  warehouse: string;
  remaining_quantity: number;
};

export type InboundAllocation = {
  id: string;
  po_code: string | null;
  delivery_no: string | null;
  inbound_no: string | null;
  site: string | null;
  warehouse: string | null;
  history_quantity: number | null;
  normal_quantity: number | null;
  overreceipt_quantity: number | null;
  current_quantity: number | null;
};

type SnapshotPurchaseOption = PurchaseOption & { supplier_code: string; sku: string };
export type PurchaseSnapshot = {
  state: "missing" | "ready" | "stale" | "unavailable";
  job: Job | null;
  snapshot_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  supplier_count: number;
  sku_count: number;
  total: number;
  items: SnapshotPurchaseOption[];
};
export type InboundAllocations = {
  items: InboundAllocation[];
  batch_updated_at: string;
  history_captured_at: string | null;
};

const snapshotPath = (batchId: number) => `/api/self-operated-batches/${batchId}/purchase-snapshot`;

export const getPurchaseSnapshot = (batchId: number, signal: AbortSignal) =>
  api<PurchaseSnapshot>(snapshotPath(batchId), { signal });

const requestPurchaseSnapshot = (batchId: number, refresh: boolean, signal: AbortSignal) =>
  api<PurchaseSnapshot>(snapshotPath(batchId), { method: "POST", body: JSON.stringify({ refresh }), signal });

export function purchaseIdentity(supplier: string, sku: string) {
  return JSON.stringify([supplier.trim().toUpperCase(), sku.trim().toUpperCase()]);
}

export async function beginPurchaseSnapshot(batchId: number, refresh: boolean, signal: AbortSignal) {
  if (refresh) return requestPurchaseSnapshot(batchId, true, signal);
  const existing = await getPurchaseSnapshot(batchId, signal);
  signal.throwIfAborted();
  return existing.job ? existing : requestPurchaseSnapshot(batchId, false, signal);
}

export function isPurchaseSnapshotActive(snapshot: PurchaseSnapshot | null) {
  const status = snapshot?.job?.status;
  return status === "queued" || status === "running";
}

async function readSnapshotPages(batchId: number, first: PurchaseSnapshot, signal: AbortSignal) {
  const items = [...first.items];
  while (items.length < first.total) {
    const query = new URLSearchParams({
      snapshot_id: first.snapshot_id ?? "",
      offset: String(items.length),
      limit: "200"
    });

    const page = await api<PurchaseSnapshot>(`${snapshotPath(batchId)}?${query}`, { signal });
    if (page.snapshot_id !== first.snapshot_id || !page.items.length) throw new Error("采购快照分页不完整，请重新读取");
    items.push(...page.items);
  }
  return { ...first, items };
}

export async function readCompletePurchaseSnapshot(batchId: number, first: PurchaseSnapshot, signal: AbortSignal) {
  try {
    return await readSnapshotPages(batchId, first, signal);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 409)) throw error;
    const latest = await getPurchaseSnapshot(batchId, signal);
    return latest.state === "ready" ? readSnapshotPages(batchId, latest, signal) : latest;
  }
}

export const getInboundAllocations = (exceptionId: number) =>
  api<InboundAllocations>(`/api/exceptions/${exceptionId}/inbound-allocation`);
