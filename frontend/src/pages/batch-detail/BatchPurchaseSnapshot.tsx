import { useContext, type ReactNode } from "react";
import { Alert, Button, theme } from "antd";
import type { Batch } from "../../types";
import { formatBeijingDateTime } from "../../dateTime";
import {
  PurchaseSnapshotContext,
  useBatchPurchaseSnapshot,
  type BatchPurchaseSnapshotState
} from "./useBatchPurchaseSnapshot";
import { isPurchaseSnapshotActive } from "../../inboundExceptionApi";

export default function BatchPurchaseSnapshot({ batch, children }: { batch: Batch; children: ReactNode }) {
  const state = useBatchPurchaseSnapshot(batch);
  return <PurchaseSnapshotContext value={state}>{children}</PurchaseSnapshotContext>;
}

function snapshotTitle(state: BatchPurchaseSnapshotState, busy: boolean) {
  const { metadata, data } = state;
  let title = busy ? "正在加载整批采购数据" : "整批采购数据尚未加载";
  if (metadata?.state === "stale") title = "批次范围已变化，请刷新整批采购数据";
  if (metadata?.state === "unavailable") title = "采购快照不可读取，请刷新整批采购数据";
  if (data)
    title = `${busy ? "正在刷新，当前" : ""}采购数据更新于：${formatBeijingDateTime(data.completed_at ?? "")}，覆盖 ${data.supplier_count} 家供应商、${data.sku_count} 个 SKU`;
  return title;
}

export function BatchPurchaseSnapshotNotice() {
  const { token } = theme.useToken();
  const state = useContext(PurchaseSnapshotContext);
  if (!state?.enabled) return null;
  const { error, loading, metadata } = state;
  const busy = loading || (!error && isPurchaseSnapshotActive(metadata));
  return (
    <Alert
      styles={{ root: { background: token.colorBgContainer, marginBottom: token.marginSM } }}
      showIcon
      type={error ? "warning" : "info"}
      title={snapshotTitle(state, busy)}
      description={error}
      action={
        <Button size="small" loading={busy} onClick={state.refresh}>
          {error ? "重试整批采购数据" : "刷新整批采购数据"}
        </Button>
      }
    />
  );
}
