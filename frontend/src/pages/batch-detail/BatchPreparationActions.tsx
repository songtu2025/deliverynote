import { Button, Upload } from "antd";
import { CloudUploadOutlined, PlayCircleOutlined } from "@ant-design/icons";
import type { Batch, Job } from "../../types";
import type { BatchFiles } from "./useBatchFiles";
import type { useBatchTasks } from "./useBatchTasks";
import { batchPresentation } from "./batchPresentation";

type PreparationProps = {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  fileActions: BatchFiles;
  tasks: ReturnType<typeof useBatchTasks>;
};

export default function BatchPreparationActions(props: PreparationProps) {
  const { batch } = props;
  const selfOperated = batch.workflow === "self_operated_inbound";
  const compute = selfOperated ? batch.status === "failed" : batch.status === "preflight_ready";
  const main = preparationAction(props, compute);
  return (
    <div className="batch-primary-actions">
      <BatchFileUploads {...props} />
      <Button type="primary" icon={<PlayCircleOutlined />} {...main} />
    </div>
  );
}

function preparationAction({ batch, activeJob, action, tasks }: PreparationProps, compute: boolean) {
  const selfOperated = batch.workflow === "self_operated_inbound";
  const next = compute ? tasks.compute : selfOperated ? tasks.preflight : tasks.preflightAndCompute;
  return {
    children: preparationLabel(batch, compute),
    "aria-label": preparationLabel(batch, compute),
    loading: ["compute", "preflight", "preflight-compute"].includes(action ?? ""),
    disabled: Boolean(activeJob || action) || !preparationReady(batch, compute),
    onClick: () => void next()
  };
}

function preparationLabel(batch: Batch, compute: boolean) {
  if (compute) return batch.status === "failed" ? "重新计算" : "开始计算";
  return "预检并计算";
}

function preparationReady(batch: Batch, compute: boolean) {
  const { canCompute, canPreflight } = batchPresentation(batch);
  if (!batch.files?.length || batch.receipt?.issue_count) return false;
  if (batch.workflow === "self_operated_inbound" && !batch.inbound_file?.uploaded) return false;
  return compute ? canCompute : canPreflight || canCompute;
}

function BatchFileUploads({ batch, action, activeJob, fileActions }: PreparationProps) {
  const { canEditFiles } = batchPresentation(batch);
  if (!canEditFiles) return null;
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <>
      <Upload accept=".xls,.xlsx" multiple showUploadList={false} customRequest={fileActions.uploadFile}>
        <Button icon={<CloudUploadOutlined />} loading={action === "upload"} disabled={Boolean(activeJob || action)}>
          {selfOperated ? "上传质检交货单" : "上传交货文件"}
        </Button>
      </Upload>
      {selfOperated && (
        <Upload accept=".xls,.xlsx" showUploadList={false} customRequest={fileActions.uploadInboundFile}>
          <Button
            icon={<CloudUploadOutlined />}
            loading={action === "upload-inbound"}
            disabled={Boolean(activeJob || action)}
          >
            上传自营仓入库单
          </Button>
        </Upload>
      )}
    </>
  );
}
