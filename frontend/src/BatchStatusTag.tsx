import { Tag } from "antd";
import { ExclamationCircleFilled } from "@ant-design/icons";

const STATUS_LABELS: Record<string, string> = {
  draft: "准备文件",
  preflight_ready: "可以计算",
  queued: "排队中",
  running: "计算中",
  succeeded: "计算完成",
  failed: "失败",
  expired: "已过期"
};

const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  preflight_ready: "success",
  queued: "processing",
  running: "processing",
  succeeded: "success",
  failed: "error",
  expired: "default"
};

export const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }));
export default function BatchStatusTag({ status }: { status: string }) {
  return (
    <Tag
      color={STATUS_COLORS[status]}
      variant={status === "failed" ? "solid" : undefined}
      icon={status === "failed" ? <ExclamationCircleFilled /> : undefined}
    >
      {STATUS_LABELS[status] ?? status}
    </Tag>
  );
}
