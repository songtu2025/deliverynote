import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";

export default function BatchSummary({ batch }: { batch: Batch }) {
  const selfOperated = batch.workflow === "self_operated_inbound";
  const { totals, computed } = batchPresentation(batch);
  return (
    <div className={`summary-strip ${computed ? "" : "summary-pending"}`}>
      <div className="summary-metric">
        <span>{selfOperated ? "质检合格总量" : "交货总量"}</span>
        <strong>{computed ? totals.delivery_total : "—"}</strong>
      </div>
      <div className="summary-metric import">
        <span>{selfOperated ? "可入库" : "可导入"}</span>
        <strong>{computed ? totals.import_total : "—"}</strong>
      </div>
      <div className="summary-metric pending">
        <span>待处理</span>
        <strong>{computed ? totals.manual_total : "—"}</strong>
      </div>
      <div className="summary-equation">
        <span>数量守恒</span>
        {computed ? (
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
