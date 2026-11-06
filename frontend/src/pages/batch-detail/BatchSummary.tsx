import { Button, Popover } from "antd";
import type { Batch } from "../../types";
import QuantityRings from "../../components/QuantityRings";
import type { ExceptionReview } from "./useExceptionReview";
import { batchPresentation } from "./batchPresentation";

type SummaryProps = {
  batch: Batch;
  reviewStats?: Pick<ExceptionReview["reviewStats"], "resolvedCount" | "totalCount">;
};

const deliveryCopy = { label: "可导入", totalLabel: "交货", reviewLabel: "已审校", region: "交货数量摘要" };
const inboundCopy = { label: "可入库", totalLabel: "本次申请", reviewLabel: "已处理", region: "入库数量摘要" };

function summaryQuantities(batch: Batch) {
  const { computed, totals } = batchPresentation(batch);
  const known = computed && Boolean(batch.summary);
  const selfOperated = batch.workflow === "self_operated_inbound";
  const copy = selfOperated ? inboundCopy : deliveryCopy;
  const total = selfOperated ? batch.receipt?.requested_total : known ? totals.delivery_total : undefined;
  const value = known ? totals.import_total : undefined;
  const conservation = `${copy.totalLabel} ${totals.delivery_total} ${totals.conserved ? "=" : "≠"} ${copy.label} ${totals.import_total} + 待处理 ${totals.manual_total}`;
  return { known, selfOperated, copy, total, value, totals, conservation };
}

function quantityText(value?: number | null) {
  return value?.toLocaleString("zh-CN") ?? "—";
}

export default function BatchSummary({ batch, reviewStats }: SummaryProps) {
  const { known, selfOperated, copy, total, value, totals, conservation } = summaryQuantities(batch);
  const progress: Partial<NonNullable<SummaryProps["reviewStats"]>> = (known ? reviewStats : undefined) ?? {};
  return (
    <section className="batch-quantity-summary" aria-label={copy.region}>
      <QuantityRings
        outer={{ label: copy.label, value, total }}
        inner={{ label: `待处理${copy.reviewLabel}`, value: progress.resolvedCount, total: progress.totalCount }}
        description={known ? conservation : "尚未计算"}
      />
      <div className="quantity-summary-values">
        <SummaryMetric label={copy.label} value={value} total={total} tone="import" />
        <SummaryMetric
          label={copy.reviewLabel}
          value={progress.resolvedCount}
          total={progress.totalCount}
          tone="review"
          unit=" 条"
        />
        <SummaryPending batch={batch} />
        {known && !totals.conserved && <strong className="conservation-bad">数量不守恒：{conservation}</strong>}
      </div>
      {selfOperated && <ReceiptDerivation batch={batch} />}
    </section>
  );
}

function SummaryMetric({
  label,
  value,
  total,
  tone,
  unit = ""
}: {
  label: string;
  value?: number | null;
  total?: number | null;
  tone: string;
  unit?: string;
}) {
  return (
    <div className="quantity-summary-line">
      <i className={`quantity-dot quantity-dot-${tone}`} aria-hidden />
      <strong>{quantityText(value)}</strong>{" "}
      <span>
        / {quantityText(total)}
        {unit}
      </span>{" "}
      <span className="quantity-summary-label">{label}</span>
    </div>
  );
}

function SummaryPending({ batch }: { batch: Batch }) {
  const { known, totals } = summaryQuantities(batch);
  const issues = batch.receipt?.issue_count ?? 0;
  return (
    <div className="quantity-summary-pending">
      {known ? `待处理 ${quantityText(totals.manual_total)} 件` : "尚未计算"}
      {!known && issues > 0 && `，${issues} 处待核对`}
    </div>
  );
}

function ReceiptDerivation({ batch }: { batch: Batch }) {
  const receipt = batch.receipt ?? {};
  return (
    <Popover
      trigger="click"
      title="本次申请"
      content={
        <div className="quantity-derivation">
          <span>
            累计实收 <strong>{quantityText(receipt.cumulative_total)}</strong>
          </span>
          <span>
            历史已入库 <strong>{quantityText(receipt.history_total)}</strong>
          </span>
          <span>
            未确认行数 <strong>{receipt.unconfirmed_count ?? 0}</strong>
          </span>
        </div>
      }
    >
      <Button type="link" className="quantity-derivation-trigger">
        累计实收 − 历史已入库
      </Button>
    </Popover>
  );
}
