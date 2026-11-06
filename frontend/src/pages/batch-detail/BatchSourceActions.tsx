import { Button, Space, Upload } from "antd";
import { CloudUploadOutlined, DownloadOutlined } from "@ant-design/icons";
import type { Batch } from "../../types";
import type { BatchFiles } from "./useBatchFiles";
import { batchCapabilities, batchStage } from "../../batchStage";
import { receiptInputBusy } from "../../receipt";
import type { ExceptionReview } from "./useExceptionReview";
import { batchResultDownload } from "./batchPresentation";

export default function BatchSourceActions({
  batch,
  actions,
  action,
  downloadResult,
  startExport,
  reviewStats
}: {
  batch: Batch;
  actions: BatchFiles;
  action: string | null;
  downloadResult: (path: string, filename: string) => Promise<void>;
  startExport: () => Promise<void>;
  reviewStats?: ExceptionReview["reviewStats"];
}) {
  const { canEditFiles, hasMultipleFiles } = batchCapabilities(batch);
  const disabled = Boolean(action) || receiptInputBusy(batch);
  const path = `/api/batches/${batch.id}/download`;
  const { sourceResult } = batchStage(batch, { action, reviewStats });
  const resultTarget = batchResultDownload(batch);
  const runResult = () => {
    if (sourceResult?.key === "generate") return void startExport();
    if (resultTarget) return void downloadResult(resultTarget.path, resultTarget.filename);
  };
  return (
    <Space>
      {canEditFiles && (
        <Upload
          accept=".xls,.xlsx"
          multiple
          showUploadList={false}
          customRequest={actions.uploadFile}
          disabled={disabled}
        >
          <Button icon={<CloudUploadOutlined aria-hidden />} loading={action === "upload"} disabled={disabled}>
            {batch.workflow === "self_operated_inbound" ? "添加质检交货单" : "添加交货文件"}
          </Button>
        </Upload>
      )}
      {batch.download_ready && hasMultipleFiles && (
        <Button
          icon={<DownloadOutlined />}
          loading={action === `download:${path}`}
          disabled={disabled}
          onClick={() => void downloadResult(path, `${batch.name}_分文件.zip`)}
        >
          下载分文件 ZIP
        </Button>
      )}
      {sourceResult && (
        <Button
          disabled={Boolean(sourceResult.disabledReason)}
          loading={action === "export" || action === `download:${resultTarget?.path}`}
          onClick={runResult}
        >
          {sourceResult.label}
        </Button>
      )}
    </Space>
  );
}
