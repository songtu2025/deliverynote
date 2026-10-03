import type { Batch } from "../../types";

export function batchPresentation(batch: Batch) {
  const totals = batch.summary ?? { delivery_total: 0, import_total: 0, manual_total: 0, conserved: true };
  const computed = batch.status === "succeeded" || batch.download_ready;
  const needsReview = computed && totals.manual_total > 0;
  const hasMultipleFiles = (batch.files?.length ?? 0) > 1;
  const mergedDownloadReady = hasMultipleFiles && batch.merged_download_ready;
  return {
    totals,
    computed,
    needsReview,
    hasMultipleFiles,
    canPreflight: ["draft", "failed"].includes(batch.status),
    canCompute: ["preflight_ready", "failed"].includes(batch.status),
    canEditFiles: ["draft", "preflight_ready", "failed"].includes(batch.status),
    needsMergedGeneration: batch.download_ready && hasMultipleFiles && !mergedDownloadReady
  };
}

export function currentBatchStep(batch: Batch) {
  const { computed, needsReview } = batchPresentation(batch);
  if (computed) return needsReview ? 3 : 4;
  if (batch.status === "queued" || batch.status === "running") return 2;
  return batch.status === "preflight_ready" ? 1 : 0;
}

export function batchFileResultName(originalName: string, selfOperated: boolean) {
  return `${originalName.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`;
}
