import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { Button, Flex, Typography } from "antd";
import type { TableProps } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { getTransferOptions, remainingTransferQuantity, transferDisabledReason } from "../../exceptionTransferApi";
import type { TransferOptions } from "../../exceptionTransferApi";
import { workspacePath } from "../../app/workspaceRoutes";
import ExceptionTransferModal from "./ExceptionTransferModal";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";

function useTransferOptions() {
  const optionsCache = useRef(new Map<number, TransferOptions>());
  const pendingOptions = useRef(new Map<number, Promise<TransferOptions>>());
  const { completed_at: completedAt, snapshot_id: snapshotId } = useContext(PurchaseSnapshotContext)?.data ?? {};
  const clearOptions = useCallback(() => {
    optionsCache.current.clear();
    pendingOptions.current.clear();
  }, []);
  useEffect(clearOptions, [completedAt, snapshotId, clearOptions]);
  const loadOptions = useCallback((id: number) => {
    const cached = optionsCache.current.get(id);
    if (cached) return Promise.resolve(cached);
    const pending = pendingOptions.current.get(id);
    if (pending) return pending;
    const request = getTransferOptions(id)
      .then((result) => {
        // 刷新前的请求完成后，不得回填旧数据。
        if (pendingOptions.current.get(id) === request) optionsCache.current.set(id, result);
        return result;
      })
      .finally(() => {
        if (pendingOptions.current.get(id) === request) pendingOptions.current.delete(id);
      });
    pendingOptions.current.set(id, request);
    return request;
  }, []);
  return { optionsCache, loadOptions, clearOptions };
}

export function useExceptionTransfer(batch: Batch | undefined, onOpen?: (id: number) => void) {
  const [selected, setSelected] = useState<DeliveryException[]>([]);
  const [open, setOpen] = useState(false);
  const { optionsCache, loadOptions, clearOptions } = useTransferOptions();
  if (!batch || batch.workflow !== "self_operated_inbound" || batch.status !== "succeeded") {
    return { rowSelection: undefined, reset: () => setSelected([]), action: null, modal: null, openRow: undefined };
  }
  const rowSelection: TableProps<DeliveryException>["rowSelection"] = {
    selectedRowKeys: selected.map((record) => record.id),
    preserveSelectedRowKeys: true,
    onChange: (_, rows) => setSelected(rows),
    getCheckboxProps: (record) => ({
      disabled: record.status !== "pending" || remainingTransferQuantity(record) <= 0
    })
  };
  const success = (id: number) => {
    clearOptions();
    setOpen(false);
    setSelected([]);
    if (onOpen) onOpen(id);
    else window.location.assign(workspacePath({ page: "batches", batchId: id }));
  };
  return {
    rowSelection,
    openRow: (record: DeliveryException) => {
      setSelected([record]);
      setOpen(true);
    },
    reset: () => setSelected([]),
    action: (
      <Flex justify="end" align="center" gap="small">
        <Typography.Text type="secondary">已选 {selected.length} 条</Typography.Text>
        <Button disabled={!selected.length || Boolean(transferDisabledReason(batch))} onClick={() => setOpen(true)}>
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
