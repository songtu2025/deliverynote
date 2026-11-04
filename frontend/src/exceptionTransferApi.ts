import { api } from "./api";
import type { DeliveryException } from "./types";
import type { PurchaseOption } from "./inboundExceptionApi";

export type TransferItem = { exception_id: number; quantity: number; full_site: string };
export type TransferOptions = {
  sites: string[];
  purchases: PurchaseOption[];
  queried_at: string | null;
  purchase_error: string | null;
};

export function remainingTransferQuantity(record: DeliveryException) {
  return record.manual_quantity - (record.transferred_quantity ?? 0);
}

export function getTransferOptions(exceptionId: number) {
  return api<TransferOptions>("/api/exceptions/" + exceptionId + "/transfer-options");
}

export function transferExceptions(batchId: number, items: TransferItem[]) {
  return api<{ id: number }>("/api/batches/" + batchId + "/exceptions/transfer-to-delivery", {
    method: "POST",
    body: JSON.stringify({ items })
  });
}
