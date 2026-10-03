import { api } from "./api";
import type { Batch, InputVersion, OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "./types";
import type { BatchWorkflow } from "./pages/batches/batchWorkspace";

export function getBatchPage(workflow: BatchWorkflow, page: number, search: string, status?: string) {
  const params = new URLSearchParams({ workflow, offset: String((page - 1) * 12), limit: "12" });
  if (search.trim()) params.set("search", search.trim());
  if (status) params.set("batch_status", status);
  return api<{ items: Batch[]; total: number; empty_draft_count: number }>(`/api/batches?${params}`);
}

export function getBatchInputVersions() {
  return api<InputVersion[]>("/api/input-versions");
}

export function getBatchOverreceiptRules(workflow: BatchWorkflow) {
  return workflow === "self_operated_inbound"
    ? api<SelfOperatedOverreceiptRuleVersion[]>("/api/self-operated-overreceipt-rule-versions")
    : api<OverreceiptRuleVersion[]>("/api/overreceipt-rule-versions");
}

export function createBatchWithFiles(workflow: BatchWorkflow, name: string, files: File[]): Promise<Batch> {
  const formData = new FormData();
  formData.append("name", name);
  files.forEach((file) => formData.append(workflow === "self_operated_inbound" ? "delivery_file" : "files", file));
  return api(workflow === "self_operated_inbound" ? "/api/self-operated-batches" : "/api/batches/with-files", {
    method: "POST",
    body: formData
  });
}

export function deleteEmptyBatches(workflow: BatchWorkflow) {
  return api<{ deleted_count: number }>(
    workflow === "self_operated_inbound" ? "/api/self-operated-batches/empty" : "/api/batches/empty",
    { method: "DELETE" }
  );
}

export function deleteBatches(batchIds: number[]) {
  return api<{ deleted_count: number; deleted_ids: number[]; file_cleanup_failed_ids: number[] }>("/api/batches", {
    method: "DELETE",
    body: JSON.stringify({ batch_ids: batchIds })
  });
}
