import { useRef, useState } from "react";

import type { PositionDraftRow } from "../../types";
import type { usePositionRowMutations } from "./usePositionRowMutations";

interface PositionDeleteConfirmationOptions {
  deleting: boolean;
  bulkDeleting: boolean;
  selectedRowIds: number[];
  mutations: Pick<ReturnType<typeof usePositionRowMutations>, "deleteRow" | "bulkDelete">;
}

export function usePositionDeleteConfirmation({
  deleting,
  bulkDeleting,
  selectedRowIds,
  mutations
}: PositionDeleteConfirmationOptions) {
  const [rowId, setRowId] = useState<number | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const keepRowOpenRef = useRef<number | null>(null);
  const keepBulkOpenRef = useRef(false);

  const reset = () => {
    setRowId(null);
    setBulkOpen(false);
    keepRowOpenRef.current = null;
    keepBulkOpenRef.current = false;
  };

  const changeRowOpen = (row: PositionDraftRow, open: boolean) => {
    if (!open && keepRowOpenRef.current === row.id) {
      keepRowOpenRef.current = null;
      return;
    }
    if (!open && deleting) return;
    setRowId(open ? row.id : null);
  };

  const confirmRow = async (row: PositionDraftRow) => {
    keepRowOpenRef.current = null;
    if (await mutations.deleteRow(row)) setRowId(null);
    else keepRowOpenRef.current = row.id;
  };

  const changeBulkOpen = (open: boolean) => {
    if (!open && keepBulkOpenRef.current) {
      keepBulkOpenRef.current = false;
      return;
    }
    if (!open && bulkDeleting) return;
    setBulkOpen(open);
  };

  const confirmBulk = async () => {
    keepBulkOpenRef.current = false;
    if (await mutations.bulkDelete(selectedRowIds)) setBulkOpen(false);
    else keepBulkOpenRef.current = true;
  };

  return { rowId, bulkOpen, changeRowOpen, confirmRow, changeBulkOpen, confirmBulk, reset };
}
