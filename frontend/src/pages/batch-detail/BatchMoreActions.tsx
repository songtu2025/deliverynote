import { useContext, useRef } from "react";
import { App, Button, Dropdown } from "antd";
import { DownOutlined } from "@ant-design/icons";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";
import type { BatchPurchaseSnapshotState } from "./useBatchPurchaseSnapshot";
import { isPurchaseSnapshotActive } from "../../inboundExceptionApi";
import { receiptRefreshConfirmation } from "./ReceiptRefreshButton";
import type { Batch } from "../../types";
import type { BatchFiles } from "./useBatchFiles";
import { batchCapabilities } from "../../batchStage";
import BatchInboundUpload from "./BatchInboundUpload";

export default function BatchMoreActions({
  disabled,
  refreshHistory,
  batch,
  fileActions,
  action
}: {
  disabled: boolean;
  refreshHistory: () => Promise<void>;
  batch: Batch;
  fileActions: BatchFiles;
  action: string | null;
}) {
  const state = useContext(PurchaseSnapshotContext);
  const { modal } = App.useApp();
  const uploadButton = useRef<HTMLButtonElement>(null);
  const items = moreItems(batch, disabled, state);
  if (!items.length) return null;
  return (
    <>
      <BatchInboundUpload
        ref={uploadButton}
        upload={fileActions.uploadInboundFile}
        disabled={disabled}
        loading={action === "upload-inbound"}
        hidden
      />
      <Dropdown
        menu={{
          items,
          onClick: ({ key }) => {
            if (key === "purchase") state?.refresh();
            else if (key === "local")
              modal.confirm({
                title: "改用本地入库单？",
                content: "将停止从积加实时取数，以上传文件为准，并作废当前核对与计算结果。",
                okText: "选择本地入库单",
                cancelText: "取消",
                onOk: () => uploadButton.current?.click()
              });
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
    </>
  );
}

function moreItems(batch: Batch, disabled: boolean, state: BatchPurchaseSnapshotState | null) {
  const items = [];
  if (batch.receipt?.captured_at)
    items.push({ key: "history", label: "同步积加入库记录", disabled: disabled || !batch.file_count });
  if (batchCapabilities(batch).canEditFiles) items.push({ key: "local", label: "改用本地入库单", disabled });
  if (state?.enabled)
    items.push({
      key: "purchase",
      label: "刷新整批采购数据",
      disabled: disabled || state.loading || (!state.error && isPurchaseSnapshotActive(state.metadata))
    });
  return items;
}
