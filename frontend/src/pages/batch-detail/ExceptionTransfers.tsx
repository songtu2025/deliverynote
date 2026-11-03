import { Space } from "antd";
import { workspacePath } from "../../app/workspaceRoutes";
import type { DeliveryException } from "../../types";

export default function ExceptionTransfers({ record }: { record: DeliveryException }) {
  if (!record.transfers?.length) return null;
  return (
    <Space orientation="vertical" size={0}>
      {record.transfers.map((transfer, index) => (
        <a key={index} href={workspacePath({ page: "batches", batchId: transfer.target_batch_id })}>
          已转 {transfer.quantity} 件 → 交货批次 #{transfer.target_batch_id}
        </a>
      ))}
    </Space>
  );
}
