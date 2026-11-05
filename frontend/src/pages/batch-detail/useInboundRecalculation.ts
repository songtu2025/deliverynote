import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { Batch, Job } from "../../types";
import type { InboundAllocations } from "../../inboundExceptionApi";

type Pending = { batchId: number; compute?: Job; exported?: Job; allocated: number };
type Options = {
  batch?: Batch;
  data: InboundAllocations | null;
  reload: () => Promise<InboundAllocations | null>;
  onSaved?: () => Promise<unknown>;
};

function allocatedTotal(data: InboundAllocations) {
  return data.items.reduce((total, row) => total + (row.current_quantity ?? 0), 0);
}

type Outcome = { error: string } | { ready: true } | null;

function sameRun(job: Job, previous?: Job) {
  return job.id === previous?.id && job.claimed_at === previous.claimed_at && job.finished_at === previous.finished_at;
}

function exportOutcome(batch: Batch, previous?: Job): Outcome {
  const job = batch.jobs?.export;
  if (!job || sameRun(job, previous)) return null;
  if (job.status === "failed") return { error: job.error_message ?? "结果生成失败，请重试" };
  return job.status === "succeeded" && batch.download_ready ? { ready: true } : null;
}

function recalculationOutcome(batch: Batch | undefined, pending: Pending): Outcome {
  if (!batch || batch.id !== pending.batchId) return null;
  const job = batch.jobs?.compute;
  if (!job || sameRun(job, pending.compute)) return null;
  if (job.status === "failed") return { error: job.error_message ?? "整批重算失败，请重试" };
  return job.status === "succeeded" ? exportOutcome(batch, pending.exported) : null;
}

export function useInboundRecalculation({ batch, data, reload, onSaved }: Options) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [feedback, setFeedback] = useState<{ error: boolean; text: string } | null>(null);
  const refreshing = useRef(false);
  const saved = async () => {
    if (batch && data) {
      setFeedback(null);
      setPending({
        batchId: batch.id,
        compute: batch.jobs?.compute,
        exported: batch.jobs?.export,
        allocated: allocatedTotal(data)
      });
    }
    try {
      if ((await onSaved?.()) === null) throw new Error("读取重算状态失败，请重试读取批次");
    } catch (failure) {
      setPending(null);
      throw failure;
    }
  };
  const finish = useEffectEvent(async (before: Pending) => {
    const updated = await reload();
    if (updated) {
      const difference = allocatedTotal(updated) - before.allocated;
      setFeedback({
        error: false,
        text: `本次分配 ${difference >= 0 ? "+" : ""}${difference}，待处理剩余 ${updated.remaining_quantity ?? 0}`
      });
    } else setFeedback({ error: true, text: "重新读取分配失败，请重试读取分配" });
    setPending(null);
    refreshing.current = false;
  });
  useEffect(() => {
    if (!pending || refreshing.current) return;
    const outcome = recalculationOutcome(batch, pending);
    if (!outcome) return;
    if ("error" in outcome) {
      setFeedback({ error: true, text: outcome.error });
      setPending(null);
      return;
    }
    refreshing.current = true;
    void finish(pending);
  }, [batch, pending]);
  return { busy: Boolean(pending), feedback, saved };
}
