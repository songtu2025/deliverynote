import { useEffect, useEffectEvent, useMemo, useRef } from "react";
import { App as AntApp } from "antd";
import { ApiError } from "../../api";
import { getBatchJob } from "../../batchDetailApi";
import type { Batch, Job } from "../../types";

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
function isActiveJob(job: Job | undefined): job is Job {
  return Boolean(job && (job.status === "queued" || job.status === "running"));
}

export function useBatchJob(batch: Batch | null, load: (silent?: boolean) => Promise<unknown>) {
  const { message } = AntApp.useApp();
  const pollingJob = useRef<number | null>(null);
  const announcedJobs = useRef(new Set<number>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const activeJob = useMemo(() => {
    const jobs = batch?.jobs;
    if (isActiveJob(jobs?.compute)) return jobs.compute;
    if (isActiveJob(jobs?.export)) return jobs.export;
    return undefined;
  }, [batch?.jobs]);

  const refreshAfterJob = useEffectEvent(() => load(true));
  const announceJob = useEffectEvent((job: Job) => {
    if (!mounted.current) return;
    if (!announcedJobs.current.has(job.id)) {
      announcedJobs.current.add(job.id);
      if (job.status === "succeeded") {
        message.success(job.kind === "compute" ? "批次计算完成" : "导出文件已生成");
      } else {
        message.error(job.error_message ?? "后台任务失败");
      }
    }
  });
  const activeJobId = activeJob?.id;
  const activeJobStatus = activeJob?.status;
  useEffect(() => {
    if (!activeJobId || pollingJob.current === activeJobId) return;
    let cancelled = false;
    pollingJob.current = activeJobId;

    const poll = async () => {
      try {
        const job = await getBatchJob(activeJobId);
        if (cancelled) return;
        if (job.status === "succeeded" || job.status === "failed") {
          pollingJob.current = null;
          await refreshAfterJob();
          announceJob(job);
          return;
        }
        await wait(1500);
        if (!cancelled) void poll();
      } catch (error) {
        pollingJob.current = null;
        if (!cancelled && !(error instanceof ApiError && error.status === 401)) {
          message.error(error instanceof Error ? error.message : "读取任务状态失败");
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (pollingJob.current === activeJobId) pollingJob.current = null;
    };
  }, [activeJobId, activeJobStatus, message]);

  return activeJob;
}
