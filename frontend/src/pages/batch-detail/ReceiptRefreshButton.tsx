import { Button, Popconfirm } from "antd";

export const receiptRefreshConfirmation = {
  title: "重新获取历史？",
  description: "会清除当前计算与导出结果，再按本批单号获取最新历史。"
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
        重新取数
      </Button>
    </Popconfirm>
  );
}
