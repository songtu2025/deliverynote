import { useRef, useState } from "react";

import type { PositionImportPreview } from "../../types";
import {
  applyImport,
  errorMessage,
  hasApiCode,
  isRevisionConflict,
  POSITION_ERROR_CODES,
  previewImport
} from "./positionDraftApi";

interface PositionImportOptions {
  draftId: number | undefined;
  disabled: boolean;
  getRevision: () => number;
  onBusyChange: (action: "import-preview" | "import-apply" | null) => void;
  onApplied: (revision: number) => void;
  onConflict: (messageText: string) => void;
}

export function usePositionImport({
  draftId,
  disabled,
  getRevision,
  onBusyChange,
  onApplied,
  onConflict
}: PositionImportOptions) {
  const [preview, setPreview] = useState<PositionImportPreview | null>(null);
  const [fileName, setFileName] = useState("");
  const [error, setError] = useState<string | null>(null);
  // 页面负责忙碌状态；此引用只拦截同一渲染周期内的重复请求。
  const inFlightRef = useRef(false);

  const reset = () => {
    setPreview(null);
    setFileName("");
    setError(null);
  };

  const previewFile = async (file: File): Promise<Error | null> => {
    if (draftId === undefined || disabled || inFlightRef.current) return new Error("草稿当前不可修改");
    inFlightRef.current = true;
    onBusyChange("import-preview");
    reset();
    try {
      const candidate = await previewImport(draftId, getRevision(), file);
      setPreview(candidate);
      setFileName(file.name ?? "Excel 文件");
      return null;
    } catch (failure) {
      const messageText = errorMessage(failure, "Excel 预览失败");
      if (isRevisionConflict(failure)) onConflict(messageText);
      else setError(messageText);
      return failure instanceof Error ? failure : new Error(messageText);
    } finally {
      inFlightRef.current = false;
      onBusyChange(null);
    }
  };

  const apply = async () => {
    if (draftId === undefined || !preview || disabled || inFlightRef.current) return;
    inFlightRef.current = true;
    onBusyChange("import-apply");
    setError(null);
    try {
      const result = await applyImport(draftId, getRevision(), preview.token);
      reset();
      onApplied(result.revision);
    } catch (failure) {
      const messageText = errorMessage(failure, "应用 Excel 替换失败");
      if (isRevisionConflict(failure)) onConflict(messageText);
      else {
        if (hasApiCode(failure, POSITION_ERROR_CODES.importPreviewExpired)) reset();
        setError(messageText);
      }
    } finally {
      inFlightRef.current = false;
      onBusyChange(null);
    }
  };

  const cancel = () => {
    if (!disabled && !inFlightRef.current) reset();
  };

  return { preview, fileName, error, previewFile, apply, cancel, reset, clearError: () => setError(null) };
}
