import { useEffect, useRef } from "react";

import { ApiError } from "../../api";
import type { PositionDraftRow } from "../../types";
import * as positionDraftApi from "./positionDraftApi";
import type { PositionRevisionResponse, PositionRowValues } from "./positionDraftApi";
import { errorMessage, isRevisionConflict } from "./positionDraftApi";
import { rowValues } from "./usePositionRowEditor";

type RowMutationAction = "save" | "copy" | "delete" | "bulk-delete";

interface PositionRowMutationOptions {
  draftId: number | undefined;
  disabled: boolean;
  getRevision: () => number;
  onBusyChange: (action: RowMutationAction | null) => void;
  onApplied: (revision: number, messageText: string) => void;
  onError: (messageText: string) => void;
  onConflict: (messageText: string) => void;
}

export function usePositionRowMutations({
  draftId,
  disabled,
  getRevision,
  onBusyChange,
  onApplied,
  onError,
  onConflict
}: PositionRowMutationOptions) {
  // 页面维护统一忙碌状态；此锁只阻止渲染更新前的重复写请求。
  const inFlightRef = useRef(false);
  const generationRef = useRef(0);

  const reset = () => {
    generationRef.current += 1;
  };

  useEffect(() => reset, []);

  const run = async (
    action: RowMutationAction,
    request: (id: number, revision: number) => Promise<PositionRevisionResponse>,
    successMessage: string
  ): Promise<boolean> => {
    if (draftId === undefined || disabled || inFlightRef.current) return false;
    inFlightRef.current = true;
    const generation = generationRef.current;
    onBusyChange(action);
    try {
      const result = await request(draftId, getRevision());
      // 请求可能已经写入服务器，但失效页面不能再接收结果或显示成功。
      if (generation !== generationRef.current) return false;
      onApplied(result.revision, successMessage);
      return true;
    } catch (failure) {
      if (generation !== generationRef.current || (failure instanceof ApiError && failure.status === 401)) return false;
      const messageText = errorMessage(failure, `${successMessage}失败`);
      if (isRevisionConflict(failure)) onConflict(messageText);
      else onError(messageText);
      return false;
    } finally {
      inFlightRef.current = false;
      onBusyChange(null);
    }
  };

  const save = (values: PositionRowValues, row: PositionDraftRow | null) =>
    run(
      "save",
      (id, revision) => {
        const payload = { revision, ...values };
        return row ? positionDraftApi.updateRow(id, row.id, payload) : positionDraftApi.createRow(id, payload);
      },
      "记录已保存"
    );

  const copy = (row: PositionDraftRow) =>
    run(
      "copy",
      (id, revision) => positionDraftApi.createRow(id, { revision, ...rowValues(row) }),
      "记录已复制到服务器草稿"
    );

  const deleteRow = (row: PositionDraftRow) =>
    run("delete", (id, revision) => positionDraftApi.deleteRow(id, row.id, revision), "记录已从服务器草稿删除");

  const bulkDelete = (rowIds: number[]) => {
    if (rowIds.length === 0) return Promise.resolve(false);
    return run(
      "bulk-delete",
      (id, revision) => positionDraftApi.deleteRows(id, revision, rowIds),
      `已删除 ${rowIds.length} 条草稿记录`
    );
  };

  return { save, copy, deleteRow, bulkDelete, reset };
}
