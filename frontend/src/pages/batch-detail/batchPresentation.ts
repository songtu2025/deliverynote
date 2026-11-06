import type { Batch, Job } from "../../types";
import type { ExceptionReview } from "./useExceptionReview";

export { batchCapabilities as batchPresentation } from "../../batchStage";
import { activeBatchTask, batchCapabilities as batchPresentation, resultDownloadAvailable } from "../../batchStage";

type ReviewStats = Pick<ExceptionReview["reviewStats"], "unfinishedCount" | "unfinishedQuantity">;

export function batchTaskPresentation(batch: Batch, activeJob?: Job, reviewStats?: ReviewStats, elapsedSeconds = 0) {
  const { computed, needsReview } = batchPresentation(batch);
  const selfOperated = batch.workflow === "self_operated_inbound";
  const running = activeBatchTask(batch, activeJob);
  if (running) return jobTaskPresentation(running, selfOperated, elapsedSeconds);
  const failure = failureTaskPresentation(batch);
  if (failure) return failure;
  if (batch.status === "queued" || batch.status === "running")
    return jobTaskPresentation({ kind: "compute", status: batch.status }, selfOperated, elapsedSeconds);
  if (computed) return reviewTaskPresentation(batch, needsReview, reviewStats);
  return preparedTaskPresentation(batch);
}

function failureTaskPresentation(batch: Batch) {
  if (batch.receipt?.issue_count)
    return {
      title: `${batch.receipt.issue_count} 处累计实收待核对，处理后即可预检`,
      description: "",
      tone: "review",
      busy: false
    };
  if (batch.status === "failed")
    return {
      title: "计算失败",
      description: failedBatchReason(batch),
      tone: "error",
      busy: false
    };
  if (batch.jobs?.export?.status === "failed")
    return { title: "结果生成失败", description: batch.jobs.export.error_message ?? "", tone: "error", busy: false };
  return null;
}

function failedBatchReason(batch: Batch) {
  return batch.error_message ?? batch.jobs?.compute?.error_message ?? batch.jobs?.prepare?.error_message ?? "";
}

function preparedTaskPresentation(batch: Batch) {
  const selfOperated = batch.workflow === "self_operated_inbound";
  const copy = selfOperated
    ? {
        emptyTitle: "还没有质检交货单",
        upload: "上传一份或多份质检交货单，按顺序处理。",
        unit: "份质检交货单",
        action: "预检并计算"
      }
    : {
        emptyTitle: "还没有交货文件",
        upload: "上传一个或多个交货 Excel，按顺序处理。",
        unit: "个文件",
        action: "预检并计算"
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
    title: count ? `${count} ${copy.unit}已上传，确认顺序后${copy.action}` : copy.emptyTitle,
    description: count ? "" : copy.upload,
    tone: "waiting",
    busy: false
  };
}

function jobTaskPresentation(
  job: Pick<Job, "kind" | "status" | "queue_position">,
  selfOperated: boolean,
  elapsedSeconds: number
) {
  const queued = job.status === "queued";
  if (selfOperated) return inboundJobTask(job, elapsedSeconds);
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

function inboundJobTask(job: Pick<Job, "kind" | "status" | "queue_position">, elapsedSeconds: number) {
  const queued = job.status === "queued";
  const step = { prepare: "正在核对累计实收（1/3", compute: "正在计算（2/3" };
  const title =
    job.kind === "prepare" || job.kind === "compute"
      ? `${step[job.kind]}，已用 ${elapsedSeconds} 秒）`
      : "正在生成结果（3/3）";
  return {
    title: queued ? (job.queue_position == null ? "排队中" : `排队中，前面还有 ${job.queue_position} 个任务`) : title,
    description: "",
    tone: queued ? "waiting" : "running",
    busy: !queued
  };
}

function reviewTaskPresentation(batch: Batch, needsReview: boolean, stats?: ReviewStats) {
  const downloadable = resultDownloadAvailable(batch);
  if (batch.workflow === "self_operated_inbound") return inboundResultTask(batch, Boolean(downloadable), stats);
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
        : downloadable
          ? "结果已生成，可以下载"
          : "审校完成，可以生成结果",
    description: "",
    tone: stats.unfinishedCount > 0 || needsReview ? "review" : "ready",
    busy: false
  };
}

function inboundResultTask(batch: Batch, downloadable: boolean, stats?: ReviewStats) {
  const pending = stats?.unfinishedCount ? `，还有 ${stats.unfinishedCount} 条待处理` : "";
  return {
    title: downloadable
      ? `结果已生成，可以下载${pending}`
      : batch.jobs?.export?.status === "stale"
        ? "需要重新生成结果"
        : exportActive(batch)
          ? "正在生成结果"
          : `可以生成结果${pending}`,
    description: "",
    tone: downloadable ? "ready" : "waiting",
    busy: false
  };
}

export function batchResultPresentation(batch: Batch, activeJob?: Job) {
  const { needsMergedGeneration } = batchPresentation(batch);
  if (activeJob?.kind === "export") return activeJob.status === "queued" ? "结果排队中" : "正在生成结果";
  if (batch.jobs?.export?.status === "stale")
    return batch.workflow === "self_operated_inbound" ? "处理有更新，需重新生成结果" : "审校有更新，需重新生成结果";
  if (resultDownloadAvailable(batch)) return "结果可下载";
  return needsMergedGeneration ? "需生成合并结果" : "尚未生成结果";
}

export function batchFileResultName(originalName: string, selfOperated: boolean) {
  return `${originalName.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`;
}

export function batchResultDownload(batch: Batch) {
  const file = batch.files?.[0];
  if (!file) return null;
  const selfOperated = batch.workflow === "self_operated_inbound";
  return batchPresentation(batch).hasMultipleFiles
    ? {
        path: `/api/batches/${batch.id}/download-merged`,
        filename: `${batch.name}_${selfOperated ? "合并积加入库" : "合并处理"}.xlsx`
      }
    : { path: `/api/batch-files/${file.id}/download`, filename: batchFileResultName(file.original_name, selfOperated) };
}

function exportActive(batch: Batch) {
  return ["queued", "running"].includes(batch.jobs?.export?.status ?? "");
}
