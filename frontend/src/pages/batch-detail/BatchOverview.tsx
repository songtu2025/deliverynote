import BatchMoreActions from "./BatchMoreActions";
import { Tag, Typography } from "antd";
import { ExclamationCircleOutlined, LoadingOutlined } from "@ant-design/icons";
import { formatBeijingDateTime } from "../../dateTime";
import type { Batch, Job } from "../../types";
import type { BatchFiles } from "./useBatchFiles";
import type { useBatchTasks } from "./useBatchTasks";
import {
  batchPresentation,
  batchResultPresentation,
  batchStagePresentation,
  batchTaskPresentation
} from "./batchPresentation";
import BatchExportActions from "./BatchExportActions";
import BatchPreparationActions from "./BatchPreparationActions";
import type { ExceptionReview } from "./useExceptionReview";
import BatchTransferSources from "./BatchTransferSources";
import { BatchPurchaseSnapshotMetadata } from "./BatchPurchaseSnapshot";

type OverviewProps = {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  fileActions: BatchFiles;
  tasks: ReturnType<typeof useBatchTasks>;
  focusReview: () => void;
  reviewStats?: ExceptionReview["reviewStats"];
  reviewError: boolean;
};

export default function BatchOverview(props: OverviewProps) {
  const { batch, activeJob, reviewStats, reviewError, tasks } = props;
  const { computed } = batchPresentation(batch);
  const stage = batchStagePresentation(batch, activeJob, reviewStats);
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <header className="batch-heading" role="region" aria-label="批次任务状态">
      <div className="batch-heading-copy">
        <div className="batch-title-row">
          <Typography.Title level={2} title={batch.name}>
            {batch.name}
          </Typography.Title>
          <Tag className={`batch-stage batch-stage-${stage.tone}`}>{stage.label}</Tag>
        </div>
        <BatchTaskStatus batch={batch} activeJob={activeJob} reviewStats={reviewStats} reviewError={reviewError} />
        <BatchMetadata batch={batch} />
        <BatchPurchaseSnapshotMetadata />
        {computed && <div className="batch-heading-meta">{batchResultPresentation(batch, activeJob)}</div>}
        <BatchTransferSources batch={batch} />
      </div>
      <div className="batch-task-actions">
        {selfOperated && (
          <BatchMoreActions
            disabled={Boolean(activeJob) || !batch.files?.length}
            refreshHistory={tasks.refreshHistory}
          />
        )}
        {computed ? <BatchExportActions {...props} /> : <BatchPreparationActions {...props} />}
      </div>
    </header>
  );
}

function BatchMetadata({ batch }: { batch: Batch }) {
  return (
    <div className="batch-heading-meta">
      {batch.files?.length ?? 0} 个来源文件 · 更新于 {formatBeijingDateTime(batch.updated_at)}
      {batch.receipt?.captured_at && <> · 历史快照 {formatBeijingDateTime(batch.receipt.captured_at)}</>}
    </div>
  );
}

function BatchTaskStatus({
  batch,
  activeJob,
  reviewStats,
  reviewError
}: Pick<OverviewProps, "batch" | "activeJob" | "reviewStats" | "reviewError">) {
  const { tone } = batchStagePresentation(batch, activeJob, reviewStats);
  const task = batchTaskPresentation(batch, activeJob, reviewStats);
  const statsName = batch.workflow === "self_operated_inbound" ? "待处理" : "审校";
  return (
    <div className="batch-task-bar">
      <div className={`batch-task-copy batch-task-${tone}`} role="status" aria-live="polite" aria-atomic="true">
        {tone === "error" && <ExclamationCircleOutlined className="batch-task-status-icon" aria-hidden />}
        {tone === "running" && <LoadingOutlined className="batch-task-status-icon batch-task-spinner" aria-hidden />}
        <span>{task.title}</span>
        {tone === "error" && task.description && <p className="batch-failure-reason">{task.description}</p>}
        {reviewError && <p>{statsName}统计暂不可用，请重试读取批次。</p>}
        {batchPresentation(batch).computed && !reviewStats && !reviewError && <p>正在读取{statsName}统计…</p>}
      </div>
    </div>
  );
}
