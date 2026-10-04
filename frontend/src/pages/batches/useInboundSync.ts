import { useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { App as AntApp } from "antd";
import {
  getInboundSyncStatus,
  startInboundSync as startInboundSyncJob,
  activateInboundSync as activateInboundSyncJob,
  downloadInboundSyncIssues
} from "../../syncApi";
import type { SelfOperatedInboundSyncStatus } from "../../types";
import type { BatchWorkflow } from "./batchWorkspace";
export function useInboundSync({
  workflow,
  active,
  status,
  setStatus,
  reload
}: {
  workflow: BatchWorkflow;
  active: boolean;
  status: SelfOperatedInboundSyncStatus | null;
  setStatus: Dispatch<SetStateAction<SelfOperatedInboundSyncStatus | null>>;
  reload: (background?: boolean, knownStatus?: SelfOperatedInboundSyncStatus) => Promise<void>;
}) {
  const { message } = AntApp.useApp();
  const [syncStarting, setSyncStarting] = useState(false);
  const [syncActivating, setSyncActivating] = useState(false);
  const [syncError, setSyncError] = useState("");
  const inboundSyncPollInFlightRef = useRef(false);
  useEffect(() => {
    const jobStatus = status?.job?.status;
    if (!active || workflow !== "self_operated_inbound" || (jobStatus !== "queued" && jobStatus !== "running")) {
      return undefined;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const pollSyncStatus = async () => {
      if (inboundSyncPollInFlightRef.current) {
        if (!cancelled) {
          timer = window.setTimeout(() => void pollSyncStatus(), 2000);
        }
        return;
      }
      inboundSyncPollInFlightRef.current = true;
      let shouldContinue = false;
      try {
        const next = await getInboundSyncStatus();
        if (cancelled) return;
        setStatus(next);
        setSyncError("");
        shouldContinue = next.job?.status === "queued" || next.job?.status === "running";
        if (!shouldContinue) {
          await reload(true, next);
        }
      } catch (error) {
        if (!cancelled) {
          setSyncError(error instanceof Error ? error.message : "读取同步状态失败");
          shouldContinue = true;
        }
      } finally {
        inboundSyncPollInFlightRef.current = false;
        if (!cancelled && shouldContinue) {
          timer = window.setTimeout(() => void pollSyncStatus(), 2000);
        }
      }
    };

    timer = window.setTimeout(() => void pollSyncStatus(), 2000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [active, reload, setStatus, status?.job?.status, workflow]);

  const startInboundSync = async () => {
    setSyncStarting(true);
    setSyncError("");
    try {
      await startInboundSyncJob();
      message.success("待入库数据同步已进入后台队列");
      await reload();
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启动同步失败");
    } finally {
      setSyncStarting(false);
    }
  };

  const activateInboundSync = async () => {
    const job = status?.job;
    if (!job?.candidate_version_id) return;
    setSyncActivating(true);
    setSyncError("");
    try {
      await activateInboundSyncJob(job.id);
      message.success("最新待入库数据已启用，将用于新批次");
      await reload();
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启用失败");
    } finally {
      setSyncActivating(false);
    }
  };

  const downloadInboundIssues = async () => {
    const job = status?.job;
    if (!job) return;
    try {
      await downloadInboundSyncIssues(job.id);
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "下载异常清单失败");
    }
  };

  const syncJob = status?.job ?? null;
  const syncRunning = syncJob?.status === "queued" || syncJob?.status === "running";
  const syncCandidateActive = Boolean(
    syncJob?.candidate_version_id && status?.active_version?.id === syncJob.candidate_version_id
  );
  return {
    syncStarting,
    syncActivating,
    syncError,
    syncJob,
    syncRunning,
    syncCandidateActive,
    startInboundSync,
    activateInboundSync,
    downloadInboundIssues
  };
}
