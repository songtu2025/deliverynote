import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";

function summaryMetrics(batch: Batch, pendingLabel: string) {
  const { totals, computed } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  const selfOperated = batch.workflow === "self_operated_inbound";
  const metrics = [
    { label: selfOperated ? "本次申请" : "交货总量", value: known ? totals.delivery_total : "—", tone: "" },
    { label: selfOperated ? "可入库" : "可导入", value: known ? totals.import_total : "—", tone: "import" },
    { label: "待处理", value: known ? totals.manual_total : pendingLabel, tone: "pending" }
  ];
  if (!selfOperated) return metrics;
  metrics[0].value = receiptValue(batch, "requested_total");
  return [
    { label: "累计实收", value: batch.receipt?.cumulative_total ?? "—", tone: "" },
    { label: "历史已入库", value: receiptValue(batch, "history_total"), tone: "" },
    ...metrics
  ];
}

function receiptValue(batch: Batch, key: "requested_total" | "history_total") {
  return batch.receipt ? (batch.receipt[key] ?? "待核对") : "—";
}

export default function BatchSummary({ batch }: { batch: Batch }) {
  const { totals, computed } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  const receiptClass = batch.workflow === "self_operated_inbound" ? "summary-receipts" : "";
  return (
    <div className={`summary-strip ${known ? "" : "summary-pending"} ${receiptClass}`}>
      {summaryMetrics(batch, receiptClass ? "计算后生成" : "—").map((metric) => (
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
