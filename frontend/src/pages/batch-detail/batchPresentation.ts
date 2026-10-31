import type { Batch, Job } from "../../types";
import type { ExceptionReview } from "./useExceptionReview";
import { receiptReady } from "../../receipt";

export function batchPresentation(batch: Batch) {
  const totals = batch.summary ?? { delivery_total: 0, import_total: 0, manual_total: 0, conserved: true };
  const computed = computedBatch(batch);
  const needsReview = computed && totals.manual_total > 0;
  const hasMultipleFiles = (batch.files?.length ?? 0) > 1;
  const mergedDownloadReady = hasMultipleFiles && batch.merged_download_ready;
  return {
    totals,
    computed,
    needsReview,
    hasMultipleFiles,
    canPreflight: ["draft", "failed"].includes(batch.status),
    canCompute: ["preflight_ready", "failed"].includes(batch.status) && receiptReady(batch),
    canEditFiles: ["draft", "preflight_ready", "failed"].includes(batch.status),
    needsMergedGeneration: batch.download_ready && hasMultipleFiles && !mergedDownloadReady
  };
}

function computedBatch(batch: Batch) {
  return (batch.status === "succeeded" || batch.download_ready) && receiptReady(batch);
}

type ReviewStats = Pick<ExceptionReview["reviewStats"], "unfinishedCount" | "unfinishedQuantity">;

export function batchTaskPresentation(batch: Batch, activeJob?: Job, reviewStats?: ReviewStats) {
  const { computed, needsReview } = batchPresentation(batch);
  if (activeJob) return jobTaskPresentation(activeJob);
  const failure = failureTaskPresentation(batch);
  if (failure) return failure;
  if (batch.status === "queued" || batch.status === "running")
    return jobTaskPresentation({ kind: "compute", status: batch.status });
  if (computed) return reviewTaskPresentation(needsReview, reviewStats);
  return preparedTaskPresentation(batch);
}

function failureTaskPresentation(batch: Batch) {
  if (batch.receipt?.issue_count)
    return {
      title: "累计实收待核对",
      description: "请查看下方累计实收核对明细，修正问题后重新预检。",
      tone: "error",
      busy: false
    };
  if (batch.status === "failed")
    return { title: "计算失败", description: "原因见下方，修正后重新预检", tone: "error", busy: false };
  if (batch.jobs?.export?.status === "failed")
    return { title: "结果生成失败", description: "审校记录已保留，可以重新生成", tone: "error", busy: false };
  return null;
}

function preparedTaskPresentation(batch: Batch) {
  const selfOperated = batch.workflow === "self_operated_inbound";
  const copy = selfOperated
    ? {
        emptyTitle: "还没有质检交货单",
        upload: "上传一份或多份质检交货单，按顺序处理。",
        unit: "份质检交货单"
      }
    : {
        emptyTitle: "还没有交货文件",
        upload: "上传一个或多个交货 Excel，按顺序处理。",
        unit: "个文件"
      };
  if (batch.status === "preflight_ready")
    return {
      title: "预检通过，可以计算",
      description: "",
      tone: "ready",
      busy: false
    };
  if (selfOperated && !batch.inbound_file?.uploaded)
    return { title: "待入库数据尚未就绪", description: "请补齐待入库数据后执行预检。", tone: "waiting", busy: false };
  const count = batch.files?.length ?? 0;
  return {
    title: count ? `${count} ${copy.unit}已上传，确认顺序后预检` : copy.emptyTitle,
    description: count ? "" : copy.upload,
    tone: "waiting",
    busy: false
  };
}

function jobTaskPresentation(job: Pick<Job, "kind" | "status">) {
  const queued = job.status === "queued";
  if (job.kind === "prepare")
    return {
      title: queued ? "历史核对排队中" : "正在获取历史并核对累计实收",
      description: "按本批交货单号取数，完成后显示累计实收、历史已入库与本次申请。",
      tone: queued ? "waiting" : "running",
      busy: !queued
    };
  const compute = job.kind === "compute";
  return {
    title: queued ? (compute ? "计算排队中" : "结果排队中") : compute ? "正在计算" : "正在生成结果",
    description: "可以先离开此页",
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
    title:
      stats.unfinishedCount > 0
        ? `${stats.unfinishedCount} 条待审校，共 ${stats.unfinishedQuantity} 件`
        : "审校完成，可以生成结果",
    description: "",
    tone: stats.unfinishedCount > 0 || needsReview ? "review" : "ready",
    busy: false
  };
}

export function batchResultPresentation(batch: Batch, activeJob?: Job) {
  const { needsMergedGeneration, hasMultipleFiles } = batchPresentation(batch);
  if (activeJob?.kind === "export") return activeJob.status === "queued" ? "结果排队中" : "正在生成结果";
  if (batch.jobs?.export?.status === "stale") return "审校有更新，需重新生成结果";
  if (resultDownloadAvailable(batch, needsMergedGeneration, hasMultipleFiles)) return "结果可下载";
  return needsMergedGeneration ? "需生成合并结果" : "尚未生成结果";
}

function resultDownloadAvailable(batch: Batch, needsMergedGeneration: boolean, hasMultipleFiles: boolean) {
  return batch.download_ready && !needsMergedGeneration && (hasMultipleFiles || batch.files?.[0]?.download_ready);
}

export function batchFileResultName(originalName: string, selfOperated: boolean) {
  return `${originalName.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`;
}
