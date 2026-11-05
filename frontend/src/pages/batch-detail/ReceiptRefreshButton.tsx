import { Button, Popconfirm } from "antd";

export const receiptRefreshConfirmation = {
  title: "同步积加入库记录？",
  description:
    "将从积加重新获取本批交货单的入库记录，并重新核对、计算整批；现有结果作废，已保存的追加超收、站点选择和线下处理保留。"
};

export default function ReceiptRefreshButton({
  disabled,
  loading,
  onConfirm,
  inline = false
}: {
  disabled: boolean;
  inline?: boolean;
  loading?: boolean;
  onConfirm: () => Promise<void>;
}) {
  return (
    <Popconfirm {...receiptRefreshConfirmation} onConfirm={onConfirm}>
      <Button color={inline ? "primary" : "default"} variant="outlined" disabled={disabled} loading={loading}>
        同步积加入库记录
      </Button>
    </Popconfirm>
  );
}
