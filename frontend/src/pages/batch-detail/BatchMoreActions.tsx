import { useContext } from "react";
import { App, Button, Dropdown } from "antd";
import { DownOutlined } from "@ant-design/icons";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";
import type { BatchPurchaseSnapshotState } from "./useBatchPurchaseSnapshot";
import { isPurchaseSnapshotActive } from "../../inboundExceptionApi";
import { receiptRefreshConfirmation } from "./ReceiptRefreshButton";
import type { Batch } from "../../types";

export default function BatchMoreActions({
  disabled,
  refreshHistory,
  batch
}: {
  disabled: boolean;
  refreshHistory: () => Promise<void>;
  batch: Batch;
}) {
  const state = useContext(PurchaseSnapshotContext);
  const { modal } = App.useApp();
  const items = moreItems(batch, disabled, state);
  if (!items.length) return null;
  return (
    <Dropdown
      menu={{
        items,
        onClick: ({ key }) => {
          if (key === "purchase") state?.refresh();
          else
            modal.confirm({
              title: receiptRefreshConfirmation.title,
              content: receiptRefreshConfirmation.description,
              okText: "同步",
              cancelText: "取消",
              onOk: refreshHistory
            });
        }
      }}
      trigger={["click"]}
    >
      <Button>
        更多 <DownOutlined />
      </Button>
    </Dropdown>
  );
}

function moreItems(batch: Batch, disabled: boolean, state: BatchPurchaseSnapshotState | null) {
  const items = [];
  if (batch.receipt?.captured_at)
    items.push({ key: "history", label: "同步积加入库记录", disabled: disabled || !batch.file_count });
  if (state?.enabled)
    items.push({
      key: "purchase",
      label: "刷新整批采购数据",
      disabled: disabled || state.loading || (!state.error && isPurchaseSnapshotActive(state.metadata))
    });
  return items;
}
