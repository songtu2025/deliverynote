import { DownloadOutlined, ExportOutlined } from "@ant-design/icons";
import type { Batch, Job } from "../../types";
import type { useBatchTasks } from "./useBatchTasks";
import type { ExceptionReview } from "./useExceptionReview";
import { batchStage } from "../../batchStage";
import { batchResultDownload } from "./batchPresentation";
import BatchPrimaryButton from "./BatchPrimaryButton";

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
  const { next, disabledReason } = batchStage(batch, { activeJob, action, reviewStats });
  const run = () => {
    if (next.key === "review") return focusReview();
    if (next.key !== "download") return void tasks.startExport();
    const target = batchResultDownload(batch);
    if (target) return void tasks.downloadResult(target.path, target.filename);
  };
  return (
    <div className="batch-result-actions">
      <BatchPrimaryButton
        icon={next.key === "download" ? <DownloadOutlined /> : <ExportOutlined />}
        reason={disabledReason}
        loading={Boolean(action)}
        onClick={run}
      >
        {next.label}
      </BatchPrimaryButton>
    </div>
  );
}
