import { Tag, Tooltip } from "antd";
import { candidateSites } from "./reviewDraft";
import type { DeliveryException } from "../../types";

const EXCEPTION_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: "未处理", color: "warning" },
  partial: { label: "部分处理", color: "processing" },
  resolved: { label: "已处理", color: "success" }
};

export function ExceptionStatusTag({ status }: { status: string }) {
  const item = EXCEPTION_STATUS[status] ?? { label: status, color: "default" };
  return <Tag color={item.color}>{item.label}</Tag>;
}

export function ExceptionReason({ reason }: { reason: string }) {
  return (
    <div className="exception-reason-cell">
      <strong>{reason}</strong>
    </div>
  );
}

function EvidenceMetric({ label, value }: { label: string; value: number }) {
  return (
    <span className="exception-evidence-metric" aria-label={`${label} ${value}`}>
      <span>{label} </span>
      <strong>{value}</strong>
    </span>
  );
}

export function ExceptionEvidence({
  exception,
  hasOverreceiptRule
}: {
  exception: DeliveryException;
  hasOverreceiptRule: boolean;
}) {
  if (exception.reason_code === "purchase_not_found") {
    return (
      <div className="exception-evidence-cell exception-evidence-check">
        <strong>需核对 </strong>
        <span>供应商、SKU、站点、目的仓</span>
      </div>
    );
  }

  if (exception.reason_code === "purchase_balance_exceeded") {
    return (
      <div className="exception-evidence-cell">
        <EvidenceMetric label="已分配" value={exception.allocated_quantity} />
        <EvidenceMetric label="超出" value={exception.manual_quantity} />
        <span className="exception-evidence-state">
          {hasOverreceiptRule ? "未命中超收规则" : "本批次未启用超收规则"}
        </span>
      </div>
    );
  }

  if (exception.reason_code === "ambiguous_product_site") {
    return (
      <div className="exception-evidence-cell">
        <strong className="exception-evidence-label">候选站点</strong>
        <div className="exception-evidence-sites">
          {candidateSites(exception.full_site).map((site) => (
            <span className="exception-evidence-site" key={site}>
              {site}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (exception.reason_code === "overreceipt_limit_exceeded") {
    const hasExactBreakdown =
      exception.purchase_allocated_quantity !== null &&
      exception.overreceipt_allocated_quantity !== null &&
      exception.overreceipt_remaining_quantity !== null;
    if (!hasExactBreakdown) {
      return (
        <div className="exception-evidence-cell">
          <span className="exception-evidence-state">历史批次暂无额度明细</span>
        </div>
      );
    }
    return (
      <div className="exception-evidence-cell">
        <EvidenceMetric label="正常采购" value={exception.purchase_allocated_quantity!} />
        <EvidenceMetric label="使用超收" value={exception.overreceipt_allocated_quantity!} />
        <EvidenceMetric label="剩余" value={exception.overreceipt_remaining_quantity!} />
      </div>
    );
  }

  return <span className="muted">查看异常原因后处理</span>;
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
