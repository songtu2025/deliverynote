import QuantityRings from "../../components/QuantityRings";
import type { Batch } from "../../types";
import { receiptReady } from "../../receipt";

export default function BatchQuantity({ batch }: { batch: Batch }) {
  const delivery = batch.workflow !== "self_operated_inbound";
  const summary = receiptReady(batch) ? batch.summary : undefined;
  const label = delivery ? "可导入" : "可入库";
  return (
    <div className="batch-table-value">
      <span className="batch-cell-label">可导入</span>
      {summary ? (
        <div className="batch-list-quantity">
          <QuantityRings
            small
            outer={{ label, value: summary.import_total, total: summary.delivery_total }}
            description={`待处理 ${summary.manual_total.toLocaleString("zh-CN")} 件`}
          />
          <div>
            <div className="batch-list-quantity-numbers">
              <strong>{summary.import_total.toLocaleString("zh-CN")}</strong>
              <span> / {summary.delivery_total.toLocaleString("zh-CN")}</span>
            </div>
            {summary.manual_total > 0 && (
              <span className="batch-list-quantity-pending">待处理 {summary.manual_total.toLocaleString("zh-CN")}</span>
            )}
          </div>
        </div>
      ) : (
        <span className="batch-volume">尚未计算</span>
      )}
      <span className="batch-volume">
        {batch.file_count} {delivery ? "个文件" : "份质检单"}
      </span>
    </div>
  );
}
