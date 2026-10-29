import type { Batch } from "./types";

export function receiptReady(batch: Batch) {
  return (
    batch.workflow !== "self_operated_inbound" || (batch.receipt?.requested_total != null && !batch.receipt.issue_count)
  );
}
