import type { Batch, Job } from "./types";
import { receiptReady } from "./receipt";

type ReviewStats = { unfinishedCount: number; unfinishedQuantity: number };
type Stage = { label: string; tone: "running" | "review" | "error" | "ready" | "waiting" };
type ActionKey = "preflight" | "compute" | "retry" | "review" | "generate" | "download" | "busy" | "expired";
type NextAction = { key: ActionKey; label: string; listLabel: string; primary: boolean };
type StageOptions = {
  activeJob?: Job;
  reviewStats?: ReviewStats;
  action?: string | null;
  hasAdjustmentDraft?: boolean;
};

function fileCount(batch: Batch) {
  return batch.files?.length ?? batch.file_count;
}

export function batchCapabilities(batch: Batch) {
  const totals = batch.summary ?? { delivery_total: 0, import_total: 0, manual_total: 0, conserved: true };
  const computed = (batch.status === "succeeded" || batch.download_ready) && receiptReady(batch);
  const hasMultipleFiles = fileCount(batch) > 1;
  return {
    totals,
    computed,
    needsReview: computed && totals.manual_total > 0,
    hasMultipleFiles,
    canPreflight: ["draft", "failed"].includes(batch.status),
    canCompute: ["preflight_ready", "failed"].includes(batch.status) && receiptReady(batch),
    canEditFiles: ["draft", "preflight_ready", "failed"].includes(batch.status),
    needsMergedGeneration: batch.download_ready && hasMultipleFiles && !batch.merged_download_ready
  };
}

export function resultDownloadAvailable(batch: Batch) {
  const { hasMultipleFiles, needsMergedGeneration } = batchCapabilities(batch);
  const invalid = ["failed", "stale", "queued", "running"].includes(batch.jobs?.export?.status ?? "");
  if (invalid || !batch.download_ready || needsMergedGeneration) return false;
  return hasMultipleFiles || !batch.files || Boolean(batch.files[0]?.download_ready);
}

export function activeBatchTask(batch: Batch, activeJob?: Job) {
  const jobs = [activeJob, batch.jobs?.prepare, batch.jobs?.compute, batch.jobs?.export];
  return jobs.find((job) => job && job.kind !== "purchase_snapshot" && ["queued", "running"].includes(job.status));
}

export function batchStage(batch: Batch, options: StageOptions = {}) {
  const running = activeBatchTask(batch, options.activeJob);
  const busy = Boolean(running || ["queued", "running"].includes(batch.status));
  const pending = options.reviewStats?.unfinishedCount ?? batch.summary?.manual_total ?? 0;
  const stage = stagePresentation(batch, running, pending);
  const next = nextPresentation(batch, stage, pending);
  if (options.hasAdjustmentDraft) next.primary = false;
  const disabledReason = busy
    ? "后台任务进行中"
    : options.action
      ? "操作进行中"
      : actionDisabledReason(batch, next, options);
  const sourceResult = next.key === "review" ? sourceResultAction(batch, options) : null;
  return { stage, next, disabledReason, pending, sourceResult };
}

function sourceResultAction(batch: Batch, options: StageOptions) {
  const next = resultAction(batch, 0);
  return { ...next, disabledReason: options.action ? "操作进行中" : actionDisabledReason(batch, next, options) };
}

function stagePresentation(batch: Batch, running: Job | undefined, pending: number): Stage {
  const active = runningStage(batch, running);
  if (active) return active;
  if (batch.receipt?.issue_count) return { label: "待核对", tone: "review" };
  if (batch.status === "failed" || batch.jobs?.export?.status === "failed") return { label: "失败", tone: "error" };
  if (batch.status === "expired") return { label: "已过期", tone: "waiting" };
  if (batchCapabilities(batch).computed) return computedStage(batch, pending);
  return preparedStage(batch);
}

function runningStage(batch: Batch, running?: Job): Stage | null {
  if (running || ["queued", "running"].includes(batch.status)) {
    const labels: Record<string, string> = { prepare: "核对中", compute: "计算中", export: "生成中" };
    return { label: labels[running?.kind ?? "compute"], tone: "running" };
  }
  return null;
}

function preparedStage(batch: Batch): Stage {
  return batch.status === "preflight_ready" && receiptReady(batch)
    ? { label: "可计算", tone: "ready" }
    : { label: "准备文件", tone: "waiting" };
}

function computedStage(batch: Batch, pending: number): Stage {
  if (pending > 0) return { label: batch.workflow === "self_operated_inbound" ? "待处理" : "待审校", tone: "review" };
  return { label: resultDownloadAvailable(batch) ? "已完成" : "可生成结果", tone: "ready" };
}

function nextPresentation(batch: Batch, stage: Stage, pending: number): NextAction {
  if (stage.tone === "running") return { key: "busy", label: stage.label, listLabel: stage.label, primary: false };
  if (batch.status === "expired") return { key: "expired", label: "查看原因", listLabel: "查看原因", primary: false };
  const next = batchCapabilities(batch).computed ? resultAction(batch, pending) : preparationAction(batch);
  if (stage.tone === "error") return { ...next, listLabel: "查看原因" };
  return next;
}

function resultAction(batch: Batch, pending: number): NextAction {
  if (batch.workflow !== "self_operated_inbound" && pending > 0 && batch.jobs?.export?.status !== "failed")
    return { key: "review", label: "开始审校", listLabel: `去审校 ${pending}`, primary: true };
  if (resultDownloadAvailable(batch)) {
    const label = batchCapabilities(batch).hasMultipleFiles ? "下载合并结果" : "下载结果";
    return { key: "download", label, listLabel: "去下载", primary: true };
  }
  return generationAction(batch);
}

function generationAction(batch: Batch): NextAction {
  const label =
    batch.jobs?.export?.status === "stale"
      ? "重新生成结果"
      : batchCapabilities(batch).needsMergedGeneration
        ? "生成合并结果"
        : "生成结果";
  return { key: "generate", label, listLabel: "去生成", primary: true };
}

function preparationAction(batch: Batch): NextAction {
  const selfOperated = batch.workflow === "self_operated_inbound";
  if (selfOperated && batch.status === "failed")
    return { key: "retry", label: "重试", listLabel: "查看原因", primary: true };
  if (!selfOperated && batch.status === "preflight_ready")
    return { key: "compute", label: "开始计算", listLabel: "去计算", primary: true };
  return { key: "preflight", label: "预检并计算", listLabel: preparationListLabel(batch), primary: false };
}

function preparationListLabel(batch: Batch) {
  if (batch.receipt?.issue_count) return "去核对";
  if (!fileCount(batch)) return "去上传";
  if (batch.workflow === "self_operated_inbound") {
    if (!batch.inbound_file?.uploaded) return "去上传";
    if (batch.status === "succeeded" && !receiptReady(batch)) return "去核对";
  }
  return "去预检并计算";
}

function actionDisabledReason(batch: Batch, next: NextAction, options: StageOptions): string | null {
  if (next.key === "expired") return "批次已过期";
  if (["preflight", "compute", "retry"].includes(next.key)) return preparationDisabledReason(batch, next.key);
  if (next.key === "generate" && batch.workflow !== "self_operated_inbound" && batch.files && !options.reviewStats)
    return "正在读取审校统计";
  return null;
}

function preparationDisabledReason(batch: Batch, key: ActionKey) {
  const inputReason = preparationInputReason(batch);
  if (inputReason) return inputReason;
  const { canCompute, canPreflight } = batchCapabilities(batch);
  if (key === "compute" && !canCompute) return "累计实收尚未核对完成";
  return canPreflight || canCompute ? null : "当前批次状态不可预检";
}

function preparationInputReason(batch: Batch) {
  if (!fileCount(batch)) return batch.workflow === "self_operated_inbound" ? "请先上传质检交货单" : "请先上传交货文件";
  if (batch.workflow === "self_operated_inbound" && !batch.inbound_file?.uploaded) return "待入库数据未就绪";
  if (batch.receipt?.issue_count) return `累计实收存在 ${batch.receipt.issue_count} 处待核对`;
  return null;
}
