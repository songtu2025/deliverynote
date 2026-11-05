import { useContext } from "react";
import { App, Button, Dropdown } from "antd";
import { DownOutlined } from "@ant-design/icons";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";
import { isPurchaseSnapshotActive } from "../../inboundExceptionApi";
import { receiptRefreshConfirmation } from "./ReceiptRefreshButton";

export default function BatchMoreActions({
  disabled,
  refreshHistory
}: {
  disabled: boolean;
  refreshHistory: () => Promise<void>;
}) {
  const state = useContext(PurchaseSnapshotContext);
  const { modal } = App.useApp();
  return (
    <Dropdown
      menu={{
        items: [
          { key: "history", label: "重新取数", disabled },
          ...(state?.enabled
            ? [
                {
                  key: "purchase",
                  label: "刷新整批采购数据",
                  disabled: state.loading || (!state.error && isPurchaseSnapshotActive(state.metadata))
                }
              ]
            : [])
        ],
        onClick: ({ key }) => {
          if (key === "purchase") state?.refresh();
          else
            modal.confirm({
              title: receiptRefreshConfirmation.title,
              content: receiptRefreshConfirmation.description,
              okText: "重新取数",
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
