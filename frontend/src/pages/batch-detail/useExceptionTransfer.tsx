import { useCallback, useRef, useState } from "react";
import { Button, Flex, Typography } from "antd";
import type { TableProps } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { getTransferOptions, remainingTransferQuantity } from "../../exceptionTransferApi";
import type { TransferOptions } from "../../exceptionTransferApi";
import { workspacePath } from "../../app/workspaceRoutes";
import ExceptionTransferModal from "./ExceptionTransferModal";

export function useExceptionTransfer(batch: Batch | undefined, onOpen?: (id: number) => void) {
  const [selected, setSelected] = useState<DeliveryException[]>([]);
  const [open, setOpen] = useState(false);
  const optionsCache = useRef(new Map<number, TransferOptions>());
  const pendingOptions = useRef(new Map<number, Promise<TransferOptions>>());
  const loadOptions = useCallback((id: number) => {
    const cached = optionsCache.current.get(id);
    if (cached) return Promise.resolve(cached);
    const pending = pendingOptions.current.get(id);
    if (pending) return pending;
    const request = getTransferOptions(id)
      .then((result) => {
        optionsCache.current.set(id, result);
        return result;
      })
      .finally(() => pendingOptions.current.delete(id));
    pendingOptions.current.set(id, request);
    return request;
  }, []);
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
    optionsCache.current.clear();
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
        optionsCache={optionsCache.current}
        loadOptions={loadOptions}
        onClose={() => setOpen(false)}
        onSuccess={success}
      />
    )
  };
}
