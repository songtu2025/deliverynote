import { Tag } from "antd";

const STATUS_LABELS: Record<string, string> = {
  draft: "准备文件",
  preflight_ready: "预检通过",
  queued: "等待计算",
  running: "正在计算",
  succeeded: "计算完成",
  failed: "处理失败",
  expired: "任务已过期"
};

const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  preflight_ready: "cyan",
  queued: "blue",
  running: "processing",
  succeeded: "success",
  failed: "error",
  expired: "warning"
};

export const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }));
export default function BatchStatusTag({ status }: { status: string }) {
  return <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status] ?? status}</Tag>;
}
