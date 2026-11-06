import { PlayCircleOutlined } from "@ant-design/icons";
import type { Batch, Job } from "../../types";
import type { useBatchTasks } from "./useBatchTasks";
import { batchStage } from "../../batchStage";
import BatchPrimaryButton from "./BatchPrimaryButton";

export default function BatchPreparationActions({
  batch,
  activeJob,
  action,
  tasks
}: {
  batch: Batch;
  activeJob?: Job;
  action: string | null;
  tasks: ReturnType<typeof useBatchTasks>;
}) {
  const { next, disabledReason } = batchStage(batch, { activeJob, action });
  const run =
    next.key === "compute"
      ? tasks.compute
      : next.key === "retry"
        ? tasks.retry
        : batch.workflow === "self_operated_inbound"
          ? tasks.preflight
          : tasks.preflightAndCompute;
  return (
    <div className="batch-primary-actions">
      <BatchPrimaryButton
        icon={<PlayCircleOutlined />}
        reason={disabledReason}
        loading={Boolean(action)}
        onClick={() => void run()}
      >
        {next.label}
      </BatchPrimaryButton>
    </div>
  );
}
