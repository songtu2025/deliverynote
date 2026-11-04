import { Space, Typography } from "antd";
import { workspacePath } from "../../app/workspaceRoutes";
import type { DeliveryException } from "../../types";

export default function ExceptionTransfers({ record }: { record: DeliveryException }) {
  if (!record.transfers?.length && !record.offline_quantity) return null;
  return (
    <Space orientation="vertical" size={0}>
      {Boolean(record.offline_quantity) && (
        <Typography.Text type="secondary" title={record.offline_note}>
          线下处理 {record.offline_quantity} 件
        </Typography.Text>
      )}
      {record.transfers?.map((transfer, index) => (
        <a key={index} href={workspacePath({ page: "batches", batchId: transfer.target_batch_id })}>
          已转 {transfer.quantity} 件 → 交货批次 #{transfer.target_batch_id}
        </a>
      ))}
    </Space>
  );
}
