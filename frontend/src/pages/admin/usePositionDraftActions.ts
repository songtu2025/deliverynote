import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api";
import type { PositionDraft } from "../../types";
import { discardDraft, downloadDraft, errorMessage, isRevisionConflict } from "./positionDraftApi";

interface PositionDraftActionsOptions {
  draft: Pick<PositionDraft, "id" | "revision"> | null;
  disabled: boolean;
  getRevision: () => number;
  onBusyChange: (action: "discard" | null) => void;
  onError: (messageText: string | null) => void;
  onConflict: (messageText: string) => void;
  onDiscarded: () => void;
}

export function usePositionDraftActions({
  draft,
  disabled,
  getRevision,
  onBusyChange,
  onError,
  onConflict,
  onDiscarded
}: PositionDraftActionsOptions) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const keepOpenRef = useRef(false);
  const inFlightRef = useRef(false);
  const generationRef = useRef(0);
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
    };
  }, []);

  const reset = () => {
    generationRef.current += 1;
    setConfirmOpen(false);
    keepOpenRef.current = false;
  };

  const changeConfirmOpen = (open: boolean) => {
    if (!open && keepOpenRef.current) {
      keepOpenRef.current = false;
      return;
    }
    if (!open && inFlightRef.current) return;
    setConfirmOpen(open);
  };

  const download = async () => {
    if (!draft) return;
    const generation = generationRef.current;
    onError(null);
    try {
      await downloadDraft(draft.id, draft.revision);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) return;
      if (generation === generationRef.current) onError(errorMessage(failure, "下载草稿失败"));
    }
  };

  const confirmDiscard = async () => {
    if (!draft || disabled || inFlightRef.current) return;
    inFlightRef.current = true;
    keepOpenRef.current = false;
    const generation = generationRef.current;
    onBusyChange("discard");
    onError(null);
    try {
      await discardDraft(draft.id, getRevision());
      // 服务端可能已经接受请求，失效页面只停止接收响应，不撤销写入。
      if (generation !== generationRef.current) return;
      setConfirmOpen(false);
      onDiscarded();
    } catch (failure) {
      if (generation !== generationRef.current || (failure instanceof ApiError && failure.status === 401)) return;
      const messageText = errorMessage(failure, "放弃草稿失败");
      if (isRevisionConflict(failure)) onConflict(messageText);
      else onError(messageText);
      keepOpenRef.current = true;
    } finally {
      inFlightRef.current = false;
      if (activeRef.current) onBusyChange(null);
    }
  };

  return { confirmOpen, changeConfirmOpen, confirmDiscard, download, reset };
}
