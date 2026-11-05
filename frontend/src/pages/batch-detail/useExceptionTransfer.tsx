import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { Button, Flex, Tooltip, Typography } from "antd";
import type { TableProps } from "antd";
import type { Batch, DeliveryException } from "../../types";
import { getTransferOptions, remainingTransferQuantity, transferDisabledReason } from "../../exceptionTransferApi";
import type { TransferOptions } from "../../exceptionTransferApi";
import { workspacePath } from "../../app/workspaceRoutes";
import ExceptionTransferModal from "./ExceptionTransferModal";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";
import InboundBulkActions from "./InboundBulkActions";

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

export function useExceptionTransfer(
  batch: Batch | undefined,
  onOpen?: (id: number) => void,
  onSaved?: () => Promise<unknown>
) {
  const [selected, setSelected] = useState<DeliveryException[]>([]);
  const [open, setOpen] = useState(false);
  const { optionsCache, loadOptions, clearOptions } = useTransferOptions();
  if (!batch || batch.workflow !== "self_operated_inbound" || batch.status !== "succeeded") {
    return { rowSelection: undefined, reset: () => setSelected([]), action: null, modal: null };
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
    reset: () => setSelected([]),
    action: selected.length > 0 && (
      <Flex justify="end" align="center" gap="small" wrap>
        <Typography.Text type="secondary">已选 {selected.length} 条</Typography.Text>
        {onSaved && (
          <InboundBulkActions
            batch={batch}
            records={selected}
            onSaved={async () => {
              setSelected([]);
              await onSaved();
            }}
          />
        )}
        <Tooltip title={selectionDisabledReason(batch, selected)} trigger={["hover", "focus"]}>
          <span tabIndex={selectionDisabledReason(batch, selected) ? 0 : undefined}>
            <Button disabled={Boolean(selectionDisabledReason(batch, selected))} onClick={() => setOpen(true)}>
              转交货批次
            </Button>
          </span>
        </Tooltip>
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

function selectionDisabledReason(batch: Batch, selected: DeliveryException[]) {
  if (selected.some((record) => ["产品信息未匹配", "产品信息站点不唯一"].includes(record.reason)))
    return "所选行需先确认产品与站点，暂不可转交货";
  return transferDisabledReason(batch);
}
