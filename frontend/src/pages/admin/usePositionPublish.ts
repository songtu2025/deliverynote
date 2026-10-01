import { useEffect, useRef, useState } from "react";

import { beijingDateTimeParts } from "../../dateTime";
import type { PositionDraftValidation } from "../../types";
import {
  errorMessage,
  hasApiCode,
  isRevisionConflict,
  POSITION_ERROR_CODES,
  publishDraft,
  validateDraft
} from "./positionDraftApi";

interface PositionPublishOptions {
  draftId: number | undefined;
  disabled: boolean;
  getRevision: () => number;
  onBusyChange: (action: "validate" | "publish" | null) => void;
  onValidationError: (messageText: string) => void;
  onPublished: (version: Awaited<ReturnType<typeof publishDraft>>) => void;
  onConflict: (messageText: string, kind: "revision" | "base") => void;
}

function defaultVersionName(): string {
  const parts = beijingDateTimeParts();
  return `position-${parts.year}${parts.month}${parts.day}-${parts.hour}${parts.minute}`;
}

export function usePositionPublish({
  draftId,
  disabled,
  getRevision,
  onBusyChange,
  onValidationError,
  onPublished,
  onConflict
}: PositionPublishOptions) {
  const [validation, setValidation] = useState<PositionDraftValidation | null>(null);
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warningsConfirmed, setWarningsConfirmed] = useState(false);
  // 页面维护统一忙碌状态，此引用只阻止同一渲染周期内重入。
  const inFlightRef = useRef(false);
  const generationRef = useRef(0);

  useEffect(
    () => () => {
      generationRef.current += 1;
    },
    []
  );

  const reset = () => {
    // 刷新、冲突或离开后，旧校验响应不能重新打开弹窗。
    generationRef.current += 1;
    setValidation(null);
    setName("");
    setNameError(null);
    setError(null);
    setWarningsConfirmed(false);
  };

  const open = async () => {
    if (draftId === undefined || disabled || inFlightRef.current) return;
    inFlightRef.current = true;
    reset();
    const generation = generationRef.current;
    const revision = getRevision();
    onBusyChange("validate");
    try {
      const result = await validateDraft(draftId);
      if (generation !== generationRef.current) return;
      if (result.revision !== revision || result.revision !== getRevision()) {
        onConflict("草稿已由其他管理员修改，请刷新后重试", "revision");
        return;
      }
      setValidation(result);
      setName(defaultVersionName());
    } catch (failure) {
      if (generation !== generationRef.current) return;
      const messageText = errorMessage(failure, "发布前校验失败");
      if (isRevisionConflict(failure)) onConflict(messageText, "revision");
      else onValidationError(messageText);
    } finally {
      inFlightRef.current = false;
      onBusyChange(null);
    }
  };

  const blocked =
    disabled ||
    !validation ||
    validation.error_count > 0 ||
    (validation.warning_count > 0 && !warningsConfirmed) ||
    !name.trim();

  const handlePublishFailure = (failure: unknown) => {
    const messageText = errorMessage(failure, "发布失败");
    const revisionConflict = isRevisionConflict(failure);
    if (revisionConflict || hasApiCode(failure, POSITION_ERROR_CODES.baseVersionChanged)) {
      reset();
      onConflict(messageText, revisionConflict ? "revision" : "base");
    } else if (hasApiCode(failure, POSITION_ERROR_CODES.versionNameExists)) setNameError(messageText);
    else setError(messageText);
  };

  const publish = async () => {
    if (draftId === undefined || blocked || !validation || inFlightRef.current) return;
    if (validation.revision !== getRevision()) {
      reset();
      onConflict("草稿已由其他管理员修改，请刷新后重试", "revision");
      return;
    }
    inFlightRef.current = true;
    const generation = generationRef.current;
    onBusyChange("publish");
    setNameError(null);
    setError(null);
    try {
      const result = await publishDraft(draftId, {
        revision: validation.revision,
        name: name.trim(),
        confirm_warnings: warningsConfirmed
      });
      if (generation !== generationRef.current) return;
      reset();
      onPublished(result);
    } catch (failure) {
      if (generation === generationRef.current) handlePublishFailure(failure);
    } finally {
      inFlightRef.current = false;
      onBusyChange(null);
    }
  };

  const cancel = () => {
    if (!disabled && !inFlightRef.current) reset();
  };

  const changeName = (value: string) => {
    if (inFlightRef.current) return;
    setName(value);
    setNameError(null);
  };

  const confirmWarnings = (confirmed: boolean) => {
    if (!inFlightRef.current) setWarningsConfirmed(confirmed);
  };

  return {
    validation,
    name,
    nameError,
    error,
    warningsConfirmed,
    blocked,
    open,
    publish,
    cancel,
    reset,
    changeName,
    confirmWarnings
  };
}
