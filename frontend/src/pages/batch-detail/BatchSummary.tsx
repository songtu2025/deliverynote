import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";

function summaryMetrics(batch: Batch, pendingLabel: string) {
  const { totals, computed } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  const selfOperated = batch.workflow === "self_operated_inbound";
  return [
    { label: selfOperated ? "本次申请" : "交货总量", value: known ? totals.delivery_total : "—", tone: "" },
    { label: selfOperated ? "可入库" : "可导入", value: known ? totals.import_total : "—", tone: "import" },
    { label: "待处理", value: known ? totals.manual_total : pendingLabel, tone: "pending" }
  ];
}

function receiptValue(batch: Batch, key: "requested_total" | "history_total") {
  return batch.receipt ? (batch.receipt[key] ?? "待核对") : "—";
}

export default function BatchSummary({ batch }: { batch: Batch }) {
  const { totals, computed } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  if (batch.workflow === "self_operated_inbound") return <InboundSummary batch={batch} />;
  if (!known) return null;
  const segments = [
    { label: "可导入", value: totals.import_total, tone: "import" },
    { label: "待处理", value: totals.manual_total, tone: "pending" }
  ];
  return (
    <div className="batch-quantity-summary">
      <div
        className="batch-quantity-bar"
        role="img"
        aria-label={segments.map(({ label, value }) => `${label} ${value}`).join("，")}
      >
        {segments.map(({ label, value, tone }) => (
          <span key={label} className={`batch-quantity-segment quantity-${tone}`} style={{ flexGrow: value }} />
        ))}
      </div>
      <div className="batch-quantity-details">
        <div className="batch-quantity-legend">
          {segments.map(({ label, value, tone }) => (
            <span key={label}>
              <i className={`batch-quantity-swatch quantity-${tone}`} aria-hidden />
              {label} <strong>{value}</strong>
            </span>
          ))}
        </div>
        <strong className={totals.conserved ? "conservation-ok" : "conservation-bad"}>
          {!totals.conserved && "数量不守恒："}交货 {totals.delivery_total} {totals.conserved ? "=" : "≠"} 可导入{" "}
          {totals.import_total} + 待处理 {totals.manual_total}
        </strong>
      </div>
    </div>
  );
}

function InboundSummary({ batch }: { batch: Batch }) {
  const { totals, computed } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  return (
    <div className="inbound-summary" aria-label="入库数量摘要">
      <div className="inbound-result-totals">
        {summaryMetrics(batch, "计算后生成")
          .slice(1)
          .map((metric) => (
            <span
              className={`inbound-total ${metric.tone} ${metric.tone === "pending" ? "pending-value" : ""}`}
              key={metric.label}
            >
              <span>{metric.label}</span> <strong>{metric.value}</strong>
              {known ? " 件" : ""}
            </span>
          ))}
      </div>
      <div className="inbound-receipt-equation">
        <span>累计实收</span> <strong>{batch.receipt?.cumulative_total ?? "—"}</strong>
        <span> − 历史已入库</span> <strong>{receiptValue(batch, "history_total")}</strong>
        <span> = </span>
        <span>本次申请</span> <strong>{receiptValue(batch, "requested_total")}</strong>
      </div>
      {known && !totals.conserved && (
        <strong className="conservation-bad">
          数量不守恒：{totals.delivery_total} ≠ {totals.import_total} + {totals.manual_total}
        </strong>
      )}
    </div>
  );
}
