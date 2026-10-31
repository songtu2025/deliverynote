import { Button, Space, Typography, Upload } from "antd";
import type { ReactNode } from "react";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloudUploadOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  SafetyCertificateOutlined
} from "@ant-design/icons";
import { formatBeijingDateTime } from "../../dateTime";
import StatusTag from "../../BatchStatusTag";
import type { Batch, Job } from "../../types";
import type { BatchFiles } from "./useBatchFiles";
import type { useBatchTasks } from "./useBatchTasks";
import { batchPresentation, batchResultPresentation, batchTaskPresentation } from "./batchPresentation";
import BatchExportActions from "./BatchExportActions";
import type { ExceptionReview } from "./useExceptionReview";

type OverviewProps = {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  fileActions: BatchFiles;
  tasks: ReturnType<typeof useBatchTasks>;
  focusReview: () => void;
  reviewStats?: ExceptionReview["reviewStats"];
  reviewError: boolean;
  extra?: ReactNode;
};

const TASK_ICONS: Record<string, typeof CheckCircleOutlined> = {
  error: ExclamationCircleOutlined,
  ready: CheckCircleOutlined
};

export default function BatchOverview(props: OverviewProps) {
  const { batch } = props;
  return (
    <>
      <div className="batch-heading">
        <div>
          <div className="batch-title-row">
            <Typography.Title level={2} title={batch.name}>
              {batch.name}
            </Typography.Title>
            <StatusTag status={batch.status} />
          </div>
          <Typography.Text type="secondary">
            {batch.files?.length ?? 0} 个来源文件，更新于 {formatBeijingDateTime(batch.updated_at)}
          </Typography.Text>
        </div>
      </div>

      <BatchTaskBar {...props} />
    </>
  );
}

function BatchTaskBar(props: OverviewProps) {
  const { batch, activeJob, reviewStats } = props;
  const { computed } = batchPresentation(batch);
  const { title, description, tone, busy } = batchTaskPresentation(batch, activeJob, reviewStats);
  const pending = busy || [batch.status, activeJob?.status].includes("queued");
  const details = overviewDescription(props, description, tone);
  const StateIcon = pending ? LoadingOutlined : (TASK_ICONS[tone] ?? ClockCircleOutlined);
  return (
    <section className="batch-task-bar" aria-label="批次任务状态">
      <div className={`batch-task-say batch-task-${pending ? "running" : tone}`}>
        <div className="batch-task-copy" role="status" aria-live="polite" aria-atomic="true">
          <div className="batch-task-icon" aria-hidden>
            <StateIcon className={pending ? "batch-task-spinner" : undefined} />
          </div>
          <div>
            <strong>{title}</strong>
            {details && <span>{details}</span>}
          </div>
        </div>
        <div className="batch-task-actions">
          <BatchPrimaryActions {...props} />
          {computed && <BatchExportActions {...props} />}
          {props.extra}
        </div>
      </div>
      {computed && (
        <p className="batch-task-result">
          <FileTextOutlined aria-hidden />
          {batchResultPresentation(batch, activeJob)}
        </p>
      )}
    </section>
  );
}

function overviewDescription({ batch, activeJob, reviewError }: OverviewProps, description: string, tone: string) {
  const { computed } = batchPresentation(batch);
  if (computed && !activeJob && reviewError) return "审校统计暂不可用，请重试读取批次。";
  if (computed && !activeJob && batch.workflow === "self_operated_inbound" && tone !== "error") return undefined;
  return description;
}

function BatchPrimaryActions({ batch, action, fileActions, tasks }: OverviewProps) {
  const files = batch.files ?? [];
  const selfOperated = batch.workflow === "self_operated_inbound";
  const { preflight, compute } = tasks;
  const { canPreflight, canCompute } = batchPresentation(batch);
  return (
    <Space wrap className="batch-primary-actions">
      <BatchFileUploads batch={batch} action={action} fileActions={fileActions} />
      {canPreflight && (
        <Button
          icon={<SafetyCertificateOutlined />}
          disabled={!files.length || (selfOperated && !batch.inbound_file?.uploaded)}
          loading={action === "preflight"}
          onClick={() => void preflight()}
        >
          预检
        </Button>
      )}
      {canCompute && (
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={action === "compute"}
          onClick={() => void compute()}
        >
          {batch.status === "failed" ? "重新计算" : "开始计算"}
        </Button>
      )}
    </Space>
  );
}

function BatchFileUploads({ batch, action, fileActions }: Pick<OverviewProps, "batch" | "action" | "fileActions">) {
  const { canEditFiles } = batchPresentation(batch);
  const selfOperated = batch.workflow === "self_operated_inbound";
  const { uploadFile, uploadInboundFile } = fileActions;
  return (
    <>
      {canEditFiles && (
        <Upload accept=".xls,.xlsx" multiple showUploadList={false} customRequest={uploadFile}>
          <Button icon={<CloudUploadOutlined />} loading={action === "upload"}>
            {selfOperated ? "上传质检交货单" : "上传交货文件"}
          </Button>
        </Upload>
      )}
      {canEditFiles && selfOperated && (
        <Upload accept=".xls,.xlsx" showUploadList={false} customRequest={uploadInboundFile}>
          <Button icon={<CloudUploadOutlined />} loading={action === "upload-inbound"}>
            上传自营仓入库单
          </Button>
        </Upload>
      )}
    </>
  );
}
