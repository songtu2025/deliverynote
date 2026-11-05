import BatchMoreActions from "./BatchMoreActions";
import { useEffect, useState } from "react";
import { Button, Tag, Typography } from "antd";
import { ExclamationCircleOutlined, LoadingOutlined } from "@ant-design/icons";
import { formatBeijingDateTime, parseApiDateTime } from "../../dateTime";
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
        <BatchTaskStatus
          batch={batch}
          activeJob={activeJob}
          reviewStats={reviewStats}
          reviewError={reviewError}
          retry={tasks.retry}
          retrying={Boolean(props.action)}
        />
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
  reviewError,
  retry,
  retrying
}: Pick<OverviewProps, "batch" | "activeJob" | "reviewStats" | "reviewError"> & {
  retry: () => Promise<void>;
  retrying: boolean;
}) {
  const { tone } = batchStagePresentation(batch, activeJob, reviewStats);
  const elapsed = useJobElapsed(batch.workflow === "self_operated_inbound" ? activeJob : undefined);
  const task = batchTaskPresentation(batch, activeJob, reviewStats, elapsed);
  return (
    <div className="batch-task-bar">
      <div className={`batch-task-copy batch-task-${tone}`} role="status" aria-live="polite" aria-atomic="true">
        {tone === "error" && <ExclamationCircleOutlined className="batch-task-status-icon" aria-hidden />}
        {tone === "running" && <LoadingOutlined className="batch-task-status-icon batch-task-spinner" aria-hidden />}
        <span>{task.title}</span>
        {tone === "error" && task.description && <p className="batch-failure-reason">{task.description}</p>}
        <ReviewStatisticsNotice batch={batch} reviewStats={reviewStats} reviewError={reviewError} />
      </div>
      {batch.workflow === "self_operated_inbound" && tone === "error" && (
        <Button aria-label="重试" loading={retrying} onClick={() => void retry()}>
          重试
        </Button>
      )}
    </div>
  );
}

function ReviewStatisticsNotice({
  batch,
  reviewStats,
  reviewError
}: Pick<OverviewProps, "batch" | "reviewStats" | "reviewError">) {
  const name = batch.workflow === "self_operated_inbound" ? "待处理" : "审校";
  if (reviewError) return <p>{name}统计暂不可用，请重试读取批次。</p>;
  return batchPresentation(batch).computed && !reviewStats ? <p>正在读取{name}统计…</p> : null;
}

function useJobElapsed(job?: Job) {
  const [now, setNow] = useState(Date.now);
  const start = job?.status === "running" ? job.claimed_at : null;
  useEffect(() => {
    if (!start) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [start]);
  return start ? Math.max(0, Math.floor((now - parseApiDateTime(start).getTime()) / 1000)) : 0;
}
