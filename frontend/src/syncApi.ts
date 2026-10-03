import { api, download } from "./api";
import type {
  PurchaseSyncIssue,
  PurchaseSyncPreview,
  PurchaseSyncStatus,
  SelfOperatedInboundSyncIssue,
  SelfOperatedInboundSyncPreview,
  SelfOperatedInboundSyncStatus
} from "./types";

export function getPurchaseSyncStatus() {
  return api<PurchaseSyncStatus>("/api/purchase-sync");
}
export function startPurchaseSync() {
  return api("/api/purchase-sync", { method: "POST" });
}
export function getPurchaseSyncPreview(jobId: number) {
  return api<PurchaseSyncPreview>(`/api/purchase-sync/${jobId}/preview?limit=100`);
}
export function getPurchaseSyncIssues(jobId: number) {
  return api<PurchaseSyncIssue[]>(`/api/purchase-sync/${jobId}/issues`);
}
export function downloadPurchaseSyncIssues(jobId: number) {
  return download(`/api/purchase-sync/${jobId}/issues/download`, `采购同步问题_${jobId}.xlsx`);
}

export function getInboundSyncStatus() {
  return api<SelfOperatedInboundSyncStatus>("/api/self-operated-inbound-sync");
}
export function startInboundSync() {
  return api("/api/self-operated-inbound-sync", { method: "POST" });
}
export function activateInboundSync(jobId: number) {
  return api(`/api/self-operated-inbound-sync/${jobId}/activate`, { method: "POST" });
}
export function getInboundSyncPreview(jobId: number) {
  return api<SelfOperatedInboundSyncPreview>(`/api/self-operated-inbound-sync/${jobId}/preview?limit=100`);
}
export function getInboundSyncIssues(jobId: number) {
  return api<SelfOperatedInboundSyncIssue[]>(`/api/self-operated-inbound-sync/${jobId}/issues`);
}
export function downloadInboundSyncIssues(jobId: number) {
  return download(`/api/self-operated-inbound-sync/${jobId}/issues/download`, `待入库同步异常_${jobId}.xlsx`);
}
