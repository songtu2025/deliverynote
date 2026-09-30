import { useRef, useState } from "react";
import { Form } from "antd";

import type { PositionDraftRow } from "../../types";
import type { PositionRowValues } from "./positionDraftApi";

type PendingLeave = "close" | "back" | null;
type SaveRecord = (values: PositionRowValues, row: PositionDraftRow | null) => Promise<boolean>;

export function rowValues(row: PositionDraftRow): PositionRowValues {
  return {
    store_site: row.store_site,
    jiaji_sku: row.jiaji_sku,
    msku: row.msku,
    scale_position: row.scale_position,
    stocking_position: row.stocking_position
  };
}

export function usePositionRowEditor(busy: boolean, onBack: () => void) {
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [editingRow, setEditingRow] = useState<PositionDraftRow | null>(null);
  const [pendingLeave, setPendingLeave] = useState<PendingLeave>(null);
  const [form] = Form.useForm<PositionRowValues>();
  const savingRef = useRef(false);

  const reset = () => {
    setOpen(false);
    setDirty(false);
    setEditingRow(null);
    setPendingLeave(null);
    if (open) form.resetFields();
  };

  const openNewRow = () => {
    setEditingRow(null);
    form.setFieldsValue({ store_site: "", jiaji_sku: "", msku: "", scale_position: "", stocking_position: "" });
    setDirty(false);
    setOpen(true);
  };

  const openEditRow = (row: PositionDraftRow) => {
    setEditingRow(row);
    form.setFieldsValue(rowValues(row));
    setDirty(false);
    setOpen(true);
  };

  const requestClose = () => {
    if (busy || savingRef.current) return;
    if (dirty) setPendingLeave("close");
    else reset();
  };

  const requestBack = () => {
    if (busy || savingRef.current) return;
    if (open && dirty) setPendingLeave("back");
    else onBack();
  };

  const confirmLeave = () => {
    if (busy || savingRef.current) return;
    const leave = pendingLeave;
    reset();
    if (leave === "back") onBack();
  };

  const cancelLeave = () => {
    if (!busy && !savingRef.current) setPendingLeave(null);
  };

  const save = async (saveRecord: SaveRecord): Promise<boolean> => {
    if (busy || savingRef.current) return false;
    // 表单校验也会异步等待，此锁只防重入，不维护另一份界面提交状态。
    savingRef.current = true;
    try {
      let values: PositionRowValues;
      try {
        values = await form.validateFields();
      } catch {
        return false;
      }
      const saved = await saveRecord(values, editingRow);
      if (saved) reset();
      return saved;
    } finally {
      savingRef.current = false;
    }
  };

  return {
    open,
    editingRow,
    pendingLeave,
    form,
    openNewRow,
    openEditRow,
    markDirty: () => setDirty(true),
    requestClose,
    requestBack,
    confirmLeave,
    cancelLeave,
    reset,
    save
  };
}
