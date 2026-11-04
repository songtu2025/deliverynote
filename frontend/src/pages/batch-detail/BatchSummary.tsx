import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";

type QuantityMetric = { label: string; value?: number | null; tone?: string; operator?: string };

function quantityMetrics(batch: Batch, known: boolean): QuantityMetric[] {
  if (batch.workflow === "self_operated_inbound")
    return [
      { label: "累计实收", value: batch.receipt?.cumulative_total },
      { label: "历史已入库", value: batch.receipt?.history_total, operator: "−" },
      { label: "本次申请", value: batch.receipt?.requested_total, operator: "=" }
    ];
  const { totals } = batchPresentation(batch);
  return [
    { label: "交货", value: known ? totals.delivery_total : undefined },
    { label: "可导入", value: known ? totals.import_total : undefined, operator: "=", tone: "import" },
    { label: "待处理", value: known ? totals.manual_total : undefined, operator: "+", tone: "pending" }
  ];
}

export default function BatchSummary({ batch }: { batch: Batch }) {
  const { computed } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  const selfOperated = batch.workflow === "self_operated_inbound";
  const segments = resultMetrics(batch, known);
  const issues = !known ? (batch.receipt?.issue_count ?? 0) : 0;
  return (
    <section className="batch-quantity-summary" aria-label={selfOperated ? "入库数量摘要" : "交货数量摘要"}>
      <div className="batch-quantity-metrics">
        <div className="batch-quantity-equation">
          {quantityMetrics(batch, known).map((metric) => (
            <div className="batch-equation-term" key={metric.label}>
              {metric.operator && (
                <span className="batch-equation-operator" aria-hidden>
                  {metric.operator}{" "}
                </span>
              )}
              <QuantityMetric {...metric} />{" "}
            </div>
          ))}
        </div>
        {selfOperated && (
          <div className="inbound-result-totals">
            {segments.map((metric) => (
              <QuantityMetric key={metric.label} {...metric} />
            ))}
          </div>
        )}
      </div>
      <QuantityBar segments={segments} known={known} issues={issues} />
      <div className="batch-quantity-details">
        <QuantityLegend segments={segments} known={known} issues={issues} />
        {known && <Conservation batch={batch} />}
      </div>
    </section>
  );
}

function resultMetrics(batch: Batch, known: boolean): QuantityMetric[] {
  const { totals } = batchPresentation(batch);
  return [
    {
      label: batch.workflow === "self_operated_inbound" ? "可入库" : "可导入",
      value: known ? totals.import_total : undefined,
      tone: "import"
    },
    { label: "待处理", value: known ? totals.manual_total : undefined, tone: "pending" }
  ];
}

function QuantityBar({ segments, known, issues }: { segments: QuantityMetric[]; known: boolean; issues: number }) {
  const label = known
    ? segments.map(({ label, value }) => `${label} ${value}`).join("，")
    : issues
      ? `${issues} 处待核对，其余未计算`
      : "尚未计算";
  return (
    <div className={`batch-quantity-bar ${known ? "" : "quantity-uncomputed"}`} role="img" aria-label={label}>
      {known
        ? segments
            .filter(({ value }) => Number(value) > 0)
            .map(({ label, value, tone }) => (
              <span
                key={label}
                className={`batch-quantity-segment quantity-${tone}`}
                style={{ flexGrow: value ?? 0 }}
              />
            ))
        : issues > 0 && <span className="batch-quantity-segment quantity-pending quantity-review-marker" />}
    </div>
  );
}

function QuantityLegend({ segments, known, issues }: { segments: QuantityMetric[]; known: boolean; issues: number }) {
  return (
    <div className="batch-quantity-legend">
      {issues > 0 ? (
        <span>
          <i className="batch-quantity-swatch quantity-pending" aria-hidden />
          待核对 <strong>{issues} 处</strong>
          <i className="batch-quantity-swatch quantity-uncomputed" aria-hidden />
          未计算
        </span>
      ) : (
        segments.map(({ label, value, tone }) => (
          <span key={label}>
            <i className={`batch-quantity-swatch ${known ? `quantity-${tone}` : "quantity-uncomputed"}`} aria-hidden />
            {label} <strong>{value ?? "—"}</strong>
          </span>
        ))
      )}
    </div>
  );
}

function Conservation({ batch }: { batch: Batch }) {
  const { totals } = batchPresentation(batch);
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <strong className={totals.conserved ? "conservation-ok" : "conservation-bad"}>
      {!totals.conserved && "数量不守恒："}
      {selfOperated ? "本次申请" : "交货"} {totals.delivery_total} {totals.conserved ? "=" : "≠"}{" "}
      {selfOperated ? "可入库" : "可导入"} {totals.import_total} + 待处理 {totals.manual_total}
    </strong>
  );
}

function QuantityMetric({ label, value, tone }: QuantityMetric) {
  return (
    <div
      className={`batch-quantity-metric ${value == null ? "quantity-unknown" : `metric-${value === 0 ? "total" : (tone ?? "total")}`}`}
    >
      <span>{label}</span> <strong>{value == null ? "—" : value.toLocaleString("zh-CN")}</strong>
    </div>
  );
}
