import { api } from "./api";
import type { DeliveryException } from "./types";
import type { PurchaseOption } from "./inboundExceptionApi";

export type TransferItem = { exception_id: number; quantity: number; full_site: string };

export function remainingTransferQuantity(record: DeliveryException) {
  return record.manual_quantity - (record.transferred_quantity ?? 0);
}

export function getTransferSites(exceptionId: number, signal: AbortSignal) {
  return api<{ sites: string[] }>("/api/exceptions/" + exceptionId + "/transfer-options", { signal });
}

export function getTransferPurchases(exceptionId: number, signal: AbortSignal) {
  return api<{ items: PurchaseOption[] }>("/api/exceptions/" + exceptionId + "/purchase-options", { signal });
}

export function transferExceptions(batchId: number, items: TransferItem[]) {
  return api<{ id: number }>("/api/batches/" + batchId + "/exceptions/transfer-to-delivery", {
    method: "POST",
    body: JSON.stringify({ items })
  });
}
