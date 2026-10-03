import { api } from "./api";
import type { Batch, BatchFile, DeliveryException, Job, SplitPart } from "./types";

export const REVIEW_PAGE_SIZE = 10;

export function getBatchDetail(batchId: number) {
  return api<Batch>(`/api/batches/${batchId}`);
}

export function getBatchJob(jobId: number) {
  return api<Job>(`/api/jobs/${jobId}`);
}

export function preflightBatch(batchId: number) {
  return api<Batch>(`/api/batches/${batchId}/preflight`, { method: "POST" });
}

export function adoptSupplierVersion(batchId: number) {
  return api<Batch>(`/api/batches/${batchId}/refresh-supplier-version`, { method: "POST" });
}

export function startBatchJob(batchId: number, kind: "compute" | "export") {
  return api<Job>(`/api/batches/${batchId}/${kind}`, { method: "POST" });
}

export function uploadBatchFile(batchId: number, file: File, kind: "delivery" | "inbound" = "delivery") {
  const body = new FormData();
  body.append("file", file);
  const path =
    kind === "inbound" ? `/api/self-operated-batches/${batchId}/inbound-file` : `/api/batches/${batchId}/files`;
  return api<Batch | BatchFile>(path, { method: "POST", body });
}

export function deleteBatchFile(batchId: number, fileId: number) {
  return api<Batch>(`/api/batches/${batchId}/files/${fileId}`, { method: "DELETE" });
}

export function reorderBatchFiles(batchId: number, ids: number[]) {
  return api<Batch>(`/api/batches/${batchId}/files/order`, { method: "PUT", body: JSON.stringify({ file_ids: ids }) });
}

export function saveExceptionSplit(exceptionId: number, parts: SplitPart[]) {
  return api<DeliveryException>(`/api/exceptions/${exceptionId}/split`, {
    method: "PUT",
    body: JSON.stringify({ parts })
  });
}

export function resolveSelfOperatedSite(exceptionId: number, site: string) {
  return api<Job>(`/api/exceptions/${exceptionId}/self-operated-site`, {
    method: "PUT",
    body: JSON.stringify({ full_site: site })
  });
}
