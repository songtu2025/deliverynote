import { Tag, Tooltip } from "antd";
import { getReasonDefinition } from "./reasonCatalog";
import type { DeliveryException } from "../../types";

const EXCEPTION_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: "未处理", color: "warning" },
  partial: { label: "部分处理", color: "processing" },
  resolved: { label: "已处理", color: "success" }
};

export function ExceptionStatusTag({ status, selfOperated = false }: { status: string; selfOperated?: boolean }) {
  const item = EXCEPTION_STATUS[status] ?? { label: status, color: "default" };
  const label = status === "pending" && !selfOperated ? "待审校" : item.label;
  return <Tag color={item.color}>{label}</Tag>;
}

export function ExceptionReason({ reason }: { reason: string }) {
  return (
    <div className="exception-reason-cell">
      <strong>{reason}</strong>
    </div>
  );
}

export function ExceptionEvidence({
  exception,
  hasOverreceiptRule,
  documentNote
}: {
  exception: DeliveryException;
  hasOverreceiptRule: boolean;
  documentNote?: string;
}) {
  const evidence = getReasonDefinition(exception.reason_code).evidence(exception, { hasOverreceiptRule, documentNote });
  return typeof evidence === "string" ? <div className="exception-evidence-cell">{evidence}</div> : evidence;
}

export function formatPositionValue(value: string | number): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (!text.startsWith("{")) return text;
  try {
    const mapping = JSON.parse(text) as Record<string, unknown>;
    if (!mapping || Array.isArray(mapping) || typeof mapping !== "object") return text;
    return Object.entries(mapping)
      .map(([msku, item]) => `${msku}：${String(item ?? "").trim() || "—"}`)
      .join("；");
  } catch {
    return text;
  }
}

export function PositionValue({ value }: { value: string | number }) {
  const display = formatPositionValue(value);
  return (
    <Tooltip title={display === "—" ? "未匹配到当前批次锁定的库位资料" : display}>
      <span className={display === "—" ? "muted" : "position-reference-value"}>{display}</span>
    </Tooltip>
  );
}
