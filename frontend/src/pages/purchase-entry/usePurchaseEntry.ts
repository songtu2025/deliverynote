import { useState } from "react";
import { App } from "antd";
import type { UploadFile, UploadProps } from "antd";

import { ApiError } from "../../api";
import { exportPurchaseEntry, previewPurchaseEntry } from "../../purchaseEntryApi";
import type { PurchaseEntryPreview, PurchaseExportMode } from "../../purchaseEntryApi";

export function usePurchaseEntry() {
  const { message } = App.useApp();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [preview, setPreview] = useState<PurchaseEntryPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<"preview" | PurchaseExportMode | null>(null);
  const busy = action !== null;
  const file = files[0]?.originFileObj;

  const selectFile: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    if (busy) return;
    setFiles(fileList.slice(-1));
    setPreview(null);
    setError(null);
  };

  const runPreview = async () => {
    if (busy || !file) return;
    setPreview(null);
    setError(null);
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("采购单仅支持 .xlsx 文件");
      return;
    }
    setAction("preview");
    try {
      setPreview(await previewPurchaseEntry(file));
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) return;
      setError(failure instanceof Error ? failure.message : "采购单校验失败，请重试");
    } finally {
      setAction(null);
    }
  };

  const exportFile = async (mode: PurchaseExportMode) => {
    if (busy || !file || !preview) return;
    setError(null);
    setAction(mode);
    try {
      await exportPurchaseEntry(file, mode, preview.versions);
      message.success("采购单已生成，开始下载");
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) return;
      setError(failure instanceof Error ? failure.message : "生成采购单失败，请重试");
    } finally {
      setAction(null);
    }
  };

  return { files, preview, error, action, busy, selectFile, runPreview, exportFile };
}
