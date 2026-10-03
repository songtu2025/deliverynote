import { useEffect, useRef, useState } from "react";
import { App as AntApp } from "antd";
import { activateInputVersion } from "../../inputVersionApi";
import { getPurchaseSyncStatus, startPurchaseSync, downloadPurchaseSyncIssues } from "../../syncApi";
import type { InputVersion, PurchaseSyncStatus } from "../../types";
export function usePurchaseSync(
  versions: InputVersion[],
  canActivate: boolean,
  refreshVersions: () => Promise<InputVersion[]>
) {
  const { message } = AntApp.useApp();
  const [syncStatus, setSyncStatus] = useState<PurchaseSyncStatus | null>(null);
  const [syncError, setSyncError] = useState("");
  const [syncStarting, setSyncStarting] = useState(false);
  const [syncActivating, setSyncActivating] = useState(false);
  const [syncAttempt, setSyncAttempt] = useState(0);
  const refreshedCandidateRef = useRef<number | null>(null);
  const versionsRef = useRef(versions);
  versionsRef.current = versions;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const loadStatus = async () => {
      try {
        const next = await getPurchaseSyncStatus();
        if (cancelled) return;
        setSyncStatus(next);
        setSyncError("");
        const candidateId = next.job?.candidate_version_id ?? null;
        if (
          next.job?.status === "succeeded" &&
          candidateId &&
          !versionsRef.current.some((version) => version.id === candidateId) &&
          refreshedCandidateRef.current !== candidateId
        ) {
          refreshedCandidateRef.current = candidateId;
          await refreshVersions();
        }
        if (next.job?.status === "queued" || next.job?.status === "running") {
          timer = setTimeout(() => void loadStatus(), 2000);
        }
      } catch (error) {
        if (!cancelled) {
          setSyncError(error instanceof Error ? error.message : "读取同步状态失败");
        }
      }
    };

    void loadStatus();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [refreshVersions, syncAttempt]);

  const syncJob = syncStatus?.job ?? null;
  const syncCandidate = syncJob?.candidate_version_id
    ? (versions.find((version) => version.id === syncJob.candidate_version_id) ?? null)
    : null;
  const running = syncJob?.status === "queued" || syncJob?.status === "running";
  const configured = syncStatus?.configured ?? true;
  const progress = syncJob?.total_orders ? Math.round((syncJob.processed_orders / syncJob.total_orders) * 100) : 0;
  const startSync = async () => {
    if (syncStarting || running) return;
    setSyncStarting(true);
    setSyncError("");
    try {
      await startPurchaseSync();
      setSyncAttempt((value) => value + 1);
      message.success("采购数据同步已进入后台队列");
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启动同步失败");
    } finally {
      setSyncStarting(false);
    }
  };

  const activateCandidate = async () => {
    if (!syncCandidate || !canActivate || syncActivating) return;
    setSyncActivating(true);
    setSyncError("");
    try {
      await activateInputVersion(syncCandidate.id);
      await refreshVersions();
      message.success(`${syncCandidate.name} 已启用，将用于新批次`);
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启用失败");
    } finally {
      setSyncActivating(false);
    }
  };

  const downloadIssues = async () => {
    if (!syncJob) return;
    try {
      await downloadPurchaseSyncIssues(syncJob.id);
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "下载问题清单失败");
    }
  };

  return {
    syncStatus,
    syncError,
    syncStarting,
    syncActivating,
    syncJob,
    syncCandidate,
    running,
    configured,
    progress,
    startSync,
    activateCandidate,
    downloadIssues
  };
}
