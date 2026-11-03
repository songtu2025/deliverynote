import { useState } from "react";
import { Button, Flex, Typography } from "antd";
import type { TableProps } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { workspacePath } from "../../app/workspaceRoutes";
import ExceptionTransferModal from "./ExceptionTransferModal";

export function useExceptionTransfer(batch: Batch | undefined, onOpen?: (id: number) => void) {
  const [selected, setSelected] = useState<DeliveryException[]>([]);
  const [open, setOpen] = useState(false);
  if (!batch || batch.workflow !== "self_operated_inbound" || batch.status !== "succeeded") {
    return { rowSelection: undefined, reset: () => setSelected([]), action: null, modal: null };
  }
  const exportStatus = batch.jobs?.export?.status ?? "";
  const rowSelection: TableProps<DeliveryException>["rowSelection"] = {
    selectedRowKeys: selected.map((record) => record.id),
    preserveSelectedRowKeys: true,
    onChange: (_, rows) => setSelected(rows),
    getCheckboxProps: (record) => ({
      disabled: record.status !== "pending" || remainingTransferQuantity(record) <= 0
    })
  };
  const success = (id: number) => {
    setOpen(false);
    setSelected([]);
    if (onOpen) onOpen(id);
    else window.location.assign(workspacePath({ page: "batches", batchId: id }));
  };
  return {
    rowSelection,
    reset: () => setSelected([]),
    action: (
      <Flex justify="end" align="center" gap="small">
        <Typography.Text type="secondary">已选 {selected.length} 条</Typography.Text>
        <Button
          disabled={!selected.length || ["queued", "running"].includes(exportStatus)}
          onClick={() => setOpen(true)}
        >
          转交货批次
        </Button>
      </Flex>
    ),
    modal: open && (
      <ExceptionTransferModal
        batchId={batch.id}
        records={selected}
        onClose={() => setOpen(false)}
        onSuccess={success}
      />
    )
  };
}
