import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../api";
import type { PositionDraft } from "../../types";
import { createOrResumeDraft, getDraft } from "./positionDraftApi";

export function usePositionDraftSession(onConflict: (messageText: string) => void) {
  const [draft, setDraft] = useState<PositionDraft | null>(null);
  const [entryLoading, setEntryLoading] = useState(true);
  const [entryError, setEntryError] = useState<string | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [metadataStale, setMetadataStale] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const entryRequestRef = useRef(0);
  const metadataRequestRef = useRef(0);
  const revisionRef = useRef(0);

  useEffect(
    () => () => {
      entryRequestRef.current += 1;
      metadataRequestRef.current += 1;
    },
    []
  );

  const getRevision = () => revisionRef.current;
  const recordRevision = (revision: number) => {
    revisionRef.current = revision;
  };

  const markConflict = (messageText: string) => {
    setConflictMessage(messageText);
    onConflict(messageText);
  };

  const mergeDraftMetadata = (summary: PositionDraft, expectedRevision: number) => {
    if (revisionRef.current !== expectedRevision) return;
    if (summary.revision > expectedRevision) {
      markConflict("草稿已被其他管理员更新，请刷新后重试");
      return;
    }
    if (summary.revision !== expectedRevision) return;
    setDraft((current) =>
      current && current.id === summary.id && current.revision === expectedRevision
        ? {
            ...current,
            status: summary.status,
            row_count: summary.row_count,
            modified_count: summary.modified_count,
            diff: summary.diff,
            issues: summary.issues,
            error_count: summary.error_count,
            warning_count: summary.warning_count,
            valid: summary.valid,
            updated_by: summary.updated_by,
            updated_at: summary.updated_at,
            active_version_id: summary.active_version_id,
            active_version_name: summary.active_version_name
          }
        : current
    );
  };

  const refreshMetadata = async (expectedRevision = getRevision()) => {
    const request = ++metadataRequestRef.current;
    setMetadataLoading(true);
    setMetadataStale(true);
    setMetadataError(null);
    try {
      const summary = await getDraft();
      if (request !== metadataRequestRef.current || getRevision() !== expectedRevision) return;
      if (summary.id !== draft?.id || summary.revision < expectedRevision) {
        setMetadataError("摘要版本与当前草稿不一致，请刷新后重试");
        return;
      }
      mergeDraftMetadata(summary, expectedRevision);
      if (summary.revision === expectedRevision) setMetadataStale(false);
    } catch (error) {
      // 写操作已返回权威修订号，摘要刷新失败不撤销已成功的修改。
      if (request === metadataRequestRef.current && !(error instanceof ApiError && error.status === 401)) {
        setMetadataError(error instanceof Error ? error.message : "读取草稿摘要失败");
      }
    } finally {
      if (request === metadataRequestRef.current) setMetadataLoading(false);
    }
  };

  const loadDraft = useCallback(async (): Promise<boolean> => {
    const request = ++entryRequestRef.current;
    metadataRequestRef.current += 1;
    setMetadataLoading(false);
    setEntryLoading(true);
    setEntryError(null);
    try {
      const nextDraft = await createOrResumeDraft();
      if (request !== entryRequestRef.current) return false;
      revisionRef.current = nextDraft.revision;
      setDraft(nextDraft);
      setConflictMessage(null);
      setMetadataError(null);
      setMetadataStale(false);
      return true;
    } catch (error) {
      if (request === entryRequestRef.current && !(error instanceof ApiError && error.status === 401)) {
        setEntryError(error instanceof Error ? error.message : "无法打开库位草稿");
      }
      return false;
    } finally {
      if (request === entryRequestRef.current) setEntryLoading(false);
    }
  }, []);

  const acceptRevision = (revision: number) => {
    recordRevision(revision);
    setDraft((current) =>
      current
        ? {
            ...current,
            revision
          }
        : current
    );
    void refreshMetadata(revision);
  };

  return {
    draft,
    entryLoading,
    entryError,
    conflictMessage,
    metadataLoading,
    metadataStale,
    metadataError,
    refreshMetadata,
    loadDraft,
    getRevision,
    recordRevision,
    acceptRevision,
    markConflict
  };
}
