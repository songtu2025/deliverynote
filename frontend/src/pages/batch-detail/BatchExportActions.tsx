import { Button } from "antd";
import { DownloadOutlined, ExportOutlined } from "@ant-design/icons";
import type { Batch, Job } from "../../types";
import type { useBatchTasks } from "./useBatchTasks";
import { batchPresentation, batchFileResultName } from "./batchPresentation";
import type { ExceptionReview } from "./useExceptionReview";

export default function BatchExportActions({
  batch,
  activeJob,
  action,
  tasks,
  focusReview,
  reviewStats
}: {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  tasks: ReturnType<typeof useBatchTasks>;
  focusReview: () => void;
  reviewStats?: ExceptionReview["reviewStats"];
}) {
  const { needsMergedGeneration } = batchPresentation(batch);
  const exportJob = batch.jobs?.export;
  const selfOperated = batch.workflow === "self_operated_inbound";
  const { canRetry, reviewing } = exportActionState(batch, reviewStats);
  const { downloadResult, startExport } = tasks;
  return (
    <div className="batch-result-actions">
      <div className="export-action-buttons">
        {batch.download_ready && !needsMergedGeneration ? (
          <ResultDownloadButtons batch={batch} primary={selfOperated || !reviewing} downloadResult={downloadResult} />
        ) : canRetry ? (
          <ExportGenerationButton
            exportJob={exportJob}
            activeJob={activeJob}
            action={action}
            needsMergedGeneration={needsMergedGeneration}
            startExport={startExport}
            primary={selfOperated || !reviewing}
            disabled={!selfOperated && !reviewStats}
          />
        ) : null}
      </div>
      {reviewing && !selfOperated && (
        <Button aria-label="开始审校" type="primary" disabled={Boolean(activeJob)} onClick={focusReview}>
          开始审校
        </Button>
      )}
    </div>
  );
}

function exportActionState(batch: Batch, stats?: ExceptionReview["reviewStats"]) {
  const { needsReview } = batchPresentation(batch);
  const exportStatus = batch.jobs?.export?.status;
  const unfinished = stats ? stats.unfinishedCount > 0 : needsReview;
  const reviewing = exportStatus !== "failed" && unfinished;
  if (batch.workflow !== "self_operated_inbound") return { reviewing, canRetry: true };
  return { reviewing, canRetry: ["failed", "stale"].includes(exportStatus ?? "") };
}

function ResultDownloadButtons({
  batch,
  primary,
  downloadResult
}: {
  batch: Batch;
  primary: boolean;
  downloadResult: (path: string, filename: string) => Promise<void>;
}) {
  const { hasMultipleFiles } = batchPresentation(batch);
  const files = batch.files ?? [];
  const selfOperated = batch.workflow === "self_operated_inbound";
  return hasMultipleFiles ? (
    <>
      <Button
        icon={<DownloadOutlined />}
        onClick={() => void downloadResult(`/api/batches/${batch.id}/download`, `${batch.name}_分文件.zip`)}
      >
        下载分文件 ZIP
      </Button>
      <Button
        type={primary ? "primary" : "default"}
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
    </>
  ) : (
    files[0]?.download_ready && (
      <Button
        type={primary ? "primary" : "default"}
        icon={<DownloadOutlined />}
        onClick={() =>
          void downloadResult(
            `/api/batch-files/${files[0].id}/download`,
            batchFileResultName(files[0].original_name, selfOperated)
          )
        }
      >
        下载结果
      </Button>
    )
  );
}

function ExportGenerationButton({
  exportJob,
  activeJob,
  action,
  needsMergedGeneration,
  startExport,
  primary,
  disabled
}: {
  exportJob?: Job;
  activeJob?: Job;
  action: string | null;
  needsMergedGeneration: boolean;
  startExport: () => Promise<void>;
  primary: boolean;
  disabled: boolean;
}) {
  return (
    <Button
      icon={<ExportOutlined />}
      type={primary ? "primary" : "default"}
      disabled={Boolean(activeJob) || disabled}
      loading={action === "export" || activeJob?.kind === "export"}
      onClick={() => void startExport()}
    >
      {exportJob?.status === "stale" ? "重新生成结果" : needsMergedGeneration ? "生成合并结果" : "生成结果"}
    </Button>
  );
}
