import { useEffect, useRef, useState } from "react";
import type { ComponentProps, KeyboardEvent } from "react";
import { App as AntApp, Button } from "antd";
import { ApiError } from "../../api";
import { deleteBatches, deleteEmptyBatches } from "../../batchListApi";
import type { useBatchList } from "./useBatchList";
import type { BatchWorkflow } from "./batchWorkspace";

export function useBatchDeletion(workflow: BatchWorkflow, active: boolean, list: ReturnType<typeof useBatchList>) {
  const { message } = AntApp.useApp();
  const { page, batches, setPage, load } = list;
  const [cleaningEmpty, setCleaningEmpty] = useState(false);
  const [selectedBatchIds, setSelectedBatchIds] = useState<number[]>([]);
  const [deletingBatchIds, setDeletingBatchIds] = useState<number[]>([]);
  const [bulkDeleteConfirmOpen, setBulkDeleteConfirmOpen] = useState(false);
  const bulkDeleteButtonRef = useRef<HTMLButtonElement>(null);
  const bulkDeleteCancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setSelectedBatchIds([]);
    setBulkDeleteConfirmOpen(false);
  }, [workflow]);

  useEffect(() => {
    if (!active || !selectedBatchIds.length) setBulkDeleteConfirmOpen(false);
  }, [active, selectedBatchIds.length]);

  const cleanEmptyBatches = async () => {
    setCleaningEmpty(true);
    try {
      const result = await deleteEmptyBatches(workflow);
      message.success(`已删除 ${result.deleted_count} 个空批次`);
      await load();
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        message.error(error instanceof Error ? error.message : "清理空批次失败");
      }
    } finally {
      setCleaningEmpty(false);
    }
  };

  const deleteSelectedBatches = async (batchIds: number[]) => {
    if (!batchIds.length) return;
    setDeletingBatchIds(batchIds);
    try {
      const result = await deleteBatches(batchIds);
      const deletedIds = new Set(result.deleted_ids);
      setSelectedBatchIds((ids) => ids.filter((id) => !deletedIds.has(id)));
      if (page > 1 && batches.every((batch) => deletedIds.has(batch.id))) {
        setPage(page - 1);
      } else {
        await load();
      }
      if (result.file_cleanup_failed_ids.length) {
        message.warning(
          `已删除 ${result.deleted_count} 个批次，但 ${result.file_cleanup_failed_ids.length} 个文件目录清理失败`
        );
      } else {
        message.success(`已永久删除 ${result.deleted_count} 个批次`);
      }
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        message.error(error instanceof Error ? error.message : "删除批次失败");
      }
    } finally {
      setDeletingBatchIds([]);
    }
  };

  const deleting = deletingBatchIds.length > 0;
  const cancelBulkDelete = () => {
    setBulkDeleteConfirmOpen(false);
    if (active && bulkDeleteButtonRef.current?.isConnected) {
      bulkDeleteButtonRef.current.focus({ preventScroll: true });
    }
  };
  const closeBulkDeleteOnEscape = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || !bulkDeleteConfirmOpen) return;
    event.preventDefault();
    event.stopPropagation();
    cancelBulkDelete();
  };
  const bulkDeleteCancelProps: ComponentProps<typeof Button> = {
    ref: bulkDeleteCancelRef,
    onKeyDown: closeBulkDeleteOnEscape
  };
  return {
    cleaningEmpty,
    selectedBatchIds,
    setSelectedBatchIds,
    deletingBatchIds,
    deleting,
    bulkDeleteConfirmOpen,
    setBulkDeleteConfirmOpen,
    bulkDeleteButtonRef,
    bulkDeleteCancelRef,
    bulkDeleteCancelProps,
    cleanEmptyBatches,
    deleteSelectedBatches,
    cancelBulkDelete,
    closeBulkDeleteOnEscape
  };
}
