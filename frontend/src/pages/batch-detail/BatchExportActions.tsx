import { Button } from "antd";
import { DownloadOutlined, ExportOutlined } from "@ant-design/icons";
import type { Batch, Job } from "../../types";
import type { useBatchTasks } from "./useBatchTasks";
import { batchPresentation, batchFileResultName } from "./batchPresentation";

export default function BatchExportActions({
  batch,
  activeJob,
  action,
  tasks,
  focusReview
}: {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  tasks: ReturnType<typeof useBatchTasks>;
  focusReview: () => void;
}) {
  const { needsReview, needsMergedGeneration } = batchPresentation(batch);
  const exportJob = batch.jobs?.export;
  const { downloadResult, startExport } = tasks;
  return (
    <div className="batch-result-actions">
      {needsReview && batch.workflow !== "self_operated_inbound" && (
        <Button aria-label="处理异常" type="primary" onClick={focusReview}>
          处理异常
        </Button>
      )}
      <div className="export-action-buttons">
        {batch.download_ready && !needsMergedGeneration ? (
          <ResultDownloadButtons batch={batch} downloadResult={downloadResult} />
        ) : (
          <ExportGenerationButton
            exportJob={exportJob}
            activeJob={activeJob}
            action={action}
            needsMergedGeneration={needsMergedGeneration}
            startExport={startExport}
          />
        )}
      </div>
    </div>
  );
}

function ResultDownloadButtons({
  batch,
  downloadResult
}: {
  batch: Batch;
  downloadResult: (path: string, filename: string) => Promise<void>;
}) {
  const { needsReview, hasMultipleFiles } = batchPresentation(batch);
  const files = batch.files ?? [];
  const selfOperated = batch.workflow === "self_operated_inbound";
  return hasMultipleFiles ? (
    <>
      <Button
        type={needsReview ? "default" : "primary"}
        icon={<DownloadOutlined />}
        onClick={() =>
          void downloadResult(
            `/api/batches/${batch.id}/download-merged`,
            `${batch.name}_${selfOperated ? "合并积加入库" : "合并处理"}.xlsx`
          )
        }
      >
        下载合并结果
      </Button>
      <Button
        icon={<DownloadOutlined />}
        onClick={() => void downloadResult(`/api/batches/${batch.id}/download`, `${batch.name}_分文件.zip`)}
      >
        下载分文件 ZIP
      </Button>
    </>
  ) : (
    files[0]?.download_ready && (
      <Button
        type={needsReview ? "default" : "primary"}
        icon={<DownloadOutlined />}
        onClick={() =>
          void downloadResult(
            `/api/batch-files/${files[0].id}/download`,
            batchFileResultName(files[0].original_name, selfOperated)
          )
        }
      >
        下载处理结果
      </Button>
    )
  );
}

function ExportGenerationButton({
  exportJob,
  activeJob,
  action,
  needsMergedGeneration,
  startExport
}: {
  exportJob?: Job;
  activeJob?: Job;
  action: string | null;
  needsMergedGeneration: boolean;
  startExport: () => Promise<void>;
}) {
  return (
    <Button
      icon={<ExportOutlined />}
      disabled={Boolean(activeJob)}
      loading={action === "export" || activeJob?.kind === "export"}
      onClick={() => void startExport()}
    >
      {exportJob?.status === "stale" ? "重新生成导出" : needsMergedGeneration ? "生成合并结果" : "生成导出"}
    </Button>
  );
}
