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
  return (
    <div className={`summary-strip ${known ? "" : "summary-pending"}`}>
      {summaryMetrics(batch, "—").map((metric) => (
        <div className={`summary-metric ${metric.tone}`} key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
        </div>
      ))}
      <div className="summary-equation">
        <span>数量守恒</span>
        {known ? (
          <strong className={totals.conserved ? "conservation-ok" : "conservation-bad"}>
            {totals.delivery_total} = {totals.import_total} + {totals.manual_total}
          </strong>
        ) : (
          <strong>尚未计算</strong>
        )}
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
