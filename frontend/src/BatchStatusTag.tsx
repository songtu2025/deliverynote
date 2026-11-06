import { Tag } from "antd";
import { ExclamationCircleFilled } from "@ant-design/icons";
import type { Batch } from "./types";
import { batchStage } from "./batchStage";

const STATUS_LABELS: Record<string, string> = {
  draft: "准备文件",
  preflight_ready: "可以计算",
  queued: "排队中",
  running: "计算中",
  succeeded: "计算完成",
  failed: "失败",
  expired: "已过期"
};

export const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }));
export default function BatchStatusTag({
  batch,
  options
}: {
  batch: Batch;
  options?: Parameters<typeof batchStage>[1];
}) {
  const { stage } = batchStage(batch, options);
  return (
    <Tag
      className={`batch-stage batch-stage-${stage.tone}`}
      icon={stage.tone === "error" ? <ExclamationCircleFilled /> : undefined}
    >
      {stage.label}
    </Tag>
  );
}
