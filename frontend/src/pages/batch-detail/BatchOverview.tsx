import { Button, Space, Spin, Steps, Typography, Upload } from "antd";
import {
  ArrowLeftOutlined,
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
import {
  batchPresentation,
  batchResultPresentation,
  batchTaskPresentation,
  currentBatchStep
} from "./batchPresentation";
import BatchExportActions from "./BatchExportActions";
import type { ExceptionReview } from "./useExceptionReview";

type OverviewProps = {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  fileActions: BatchFiles;
  tasks: ReturnType<typeof useBatchTasks>;
  onBack: () => void;
  focusReview: () => void;
  reviewStats?: ExceptionReview["reviewStats"];
  reviewError: boolean;
};

export default function BatchOverview(props: OverviewProps) {
  const { batch, onBack } = props;
  const { computed } = batchPresentation(batch);
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <>
      <div className="batch-heading">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack} className="back-link">
            返回批次列表
          </Button>
          <div className="batch-title-row">
            <Typography.Title level={2} title={batch.name}>
              {batch.name}
            </Typography.Title>
            {selfOperated && <StatusTag status={batch.status} />}
          </div>
          <Typography.Text type="secondary">
            批次 #{batch.id} · 更新于 {formatBeijingDateTime(batch.updated_at)}
          </Typography.Text>
        </div>
        {selfOperated && <BatchPrimaryActions {...props} />}
      </div>

      {selfOperated ? (
        <>
          <SelfOperatedSteps batch={batch} activeJob={props.activeJob} />
          {computed && <BatchExportActions {...props} />}
        </>
      ) : (
        <DeliveryTaskBar {...props} />
      )}
    </>
  );
}

function SelfOperatedSteps({ batch, activeJob }: { batch: Batch; activeJob?: Job }) {
  const { computed, totals } = batchPresentation(batch);
  const currentStep = currentBatchStep(batch);
  const workflowItems = [
    { title: "准备文件", content: preparedFileLabel(batch) },
    { title: "预检", content: currentStep > 1 || batch.status === "preflight_ready" ? "检查通过" : "检查格式与供应商" },
    { title: "计算结果", content: computed ? "计算完成" : activeJob?.kind === "compute" ? "后台处理中" : "等待计算" },
    { title: "异常审校", content: computed ? `${totals.manual_total} 待处理` : "计算后开始" },
    { title: "导出下载", content: batch.download_ready ? "文件已生成" : "等待生成" }
  ];
  return (
    <div className="workflow-surface" role="group" aria-label="批次处理流程">
      <Steps
        current={currentStep}
        status={batch.status === "failed" ? "error" : "process"}
        responsive={false}
        items={workflowItems}
      />
    </div>
  );
}

function DeliveryTaskBar(props: OverviewProps) {
  const { batch, activeJob, reviewStats } = props;
  const { computed } = batchPresentation(batch);
  const { title, description, tone, busy } = batchTaskPresentation(batch, activeJob, reviewStats);
  const StateIcon = busy
    ? LoadingOutlined
    : tone === "error"
      ? ExclamationCircleOutlined
      : tone === "ready"
        ? CheckCircleOutlined
        : ClockCircleOutlined;
  return (
    <section className="batch-task-bar" aria-label="批次任务状态">
      <div className={`batch-task-copy batch-task-${tone}`} role="status" aria-live="polite" aria-atomic="true">
        <StateIcon className={busy ? "batch-task-spinner" : undefined} aria-hidden />
        <div>
          <strong>{title}</strong>
          <span>
            {computed && !activeJob && props.reviewError ? "审校统计暂不可用，请重试读取批次。" : description}
          </span>
        </div>
      </div>
      <div className="batch-task-actions">
        <BatchPrimaryActions {...props} />
        {computed && <BatchExportActions {...props} />}
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

function preparedFileLabel(batch: Batch) {
  const count = batch.files?.length ?? 0;
  if (batch.workflow === "self_operated_inbound")
    return `${count} 份质检单 + ${batch.inbound_file?.uploaded ? 1 : 0} 份待入库数据`;
  return count ? `${count} 个文件` : "等待上传";
}

function BatchPrimaryActions({ batch, activeJob, action, fileActions, tasks }: OverviewProps) {
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
          执行预检
        </Button>
      )}
      {canCompute && (
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={action === "compute"}
          onClick={() => void compute()}
        >
          {batch.status === "failed" ? "重新计算" : "启动计算"}
        </Button>
      )}
      {selfOperated && <SelfOperatedJobIndicator job={activeJob} />}
    </Space>
  );
}

function SelfOperatedJobIndicator({ job }: { job?: Job }) {
  return job ? (
    <span className="job-indicator" role="status">
      <Spin size="small" /> {job.kind === "compute" ? "正在计算" : "正在导出"}
    </span>
  ) : null;
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
