import type { Batch, Job } from "../../types";
import type { ExceptionReview } from "./useExceptionReview";

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

type ReviewStats = Pick<ExceptionReview["reviewStats"], "unfinishedCount" | "unfinishedQuantity">;

export function batchTaskPresentation(batch: Batch, activeJob?: Job, reviewStats?: ReviewStats) {
  const { computed, needsReview } = batchPresentation(batch);
  if (activeJob) return jobTaskPresentation(activeJob);
  if (batch.status === "queued" || batch.status === "running")
    return jobTaskPresentation({ kind: "compute", status: batch.status });
  if (batch.status === "failed")
    return { title: "任务执行失败", description: "查看下方错误信息，修正后重试。", tone: "error", busy: false };
  if (batch.jobs?.export?.status === "failed")
    return { title: "结果生成失败", description: "可重新生成导出；已有审校记录仍然保留。", tone: "error", busy: false };
  if (computed) return reviewTaskPresentation(needsReview, reviewStats);
  return preparedTaskPresentation(batch);
}

function preparedTaskPresentation(batch: Batch) {
  if (batch.status === "preflight_ready")
    return { title: "预检通过，可以计算", description: "按当前文件顺序连续扣减采购余额。", tone: "ready", busy: false };
  const count = batch.files?.length ?? 0;
  return {
    title: count ? "文件已准备，等待预检" : "等待上传交货文件",
    description: count ? `${count} 个来源文件 · 请确认处理顺序后执行预检。` : "上传一个或多个交货 Excel，按顺序处理。",
    tone: "waiting",
    busy: false
  };
}

function jobTaskPresentation(job: Pick<Job, "kind" | "status">) {
  const queued = job.status === "queued";
  const compute = job.kind === "compute";
  return {
    title: queued ? (compute ? "计算任务排队中" : "导出任务排队中") : compute ? "正在计算" : "正在生成结果",
    description: "可以离开页面，返回后会恢复实际任务状态。",
    tone: queued ? "waiting" : "running",
    busy: !queued
  };
}

function reviewTaskPresentation(needsReview: boolean, stats?: ReviewStats) {
  if (!stats)
    return {
      title: "计算完成",
      description: "正在读取审校统计…",
      tone: "waiting",
      busy: false
    };
  return {
    title: stats.unfinishedCount > 0 ? "等待人工审校" : "审校已完成",
    description: `${stats.unfinishedCount} 条未完成 · 待处理 ${stats.unfinishedQuantity} 件`,
    tone: stats.unfinishedCount > 0 || needsReview ? "review" : "ready",
    busy: false
  };
}

export function batchResultPresentation(batch: Batch, activeJob?: Job) {
  const { needsMergedGeneration, hasMultipleFiles } = batchPresentation(batch);
  if (activeJob?.kind === "export") return activeJob.status === "queued" ? "结果文件等待生成" : "结果文件正在生成";
  if (batch.jobs?.export?.status === "stale") return "审校已更新，需要重新生成结果";
  if (resultDownloadAvailable(batch, needsMergedGeneration, hasMultipleFiles)) return "当前结果文件已生成，可下载";
  return needsMergedGeneration ? "单文件结果已生成，需要生成合并结果" : "需要生成结果";
}

function resultDownloadAvailable(batch: Batch, needsMergedGeneration: boolean, hasMultipleFiles: boolean) {
  return batch.download_ready && !needsMergedGeneration && (hasMultipleFiles || batch.files?.[0]?.download_ready);
}

export function batchFileResultName(originalName: string, selfOperated: boolean) {
  return `${originalName.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`;
}
