import { createContext, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getPurchaseSnapshot,
  beginPurchaseSnapshot,
  isPurchaseSnapshotActive,
  purchaseIdentity,
  readCompletePurchaseSnapshot,
  type PurchaseSnapshot,
  type PurchaseOption
} from "../../inboundExceptionApi";
import type { Batch } from "../../types";

type SnapshotState = {
  scope: string;
  data: PurchaseSnapshot | null;
  metadata: PurchaseSnapshot | null;
  loading: boolean;
  error: string | null;
};

export type BatchPurchaseSnapshotState = ReturnType<typeof useBatchPurchaseSnapshot>;
export const PurchaseSnapshotContext = createContext<BatchPurchaseSnapshotState | null>(null);

function receivedState(scope: string, reply: PurchaseSnapshot, loaded: PurchaseSnapshot | null): SnapshotState {
  const data = reply.state === "ready" && loaded?.state === "ready" ? loaded : null;
  return {
    scope,
    data,
    metadata: reply,
    loading: !data && isPurchaseSnapshotActive(reply),
    error: reply.job?.status === "failed" ? (reply.job.error_message ?? "整批采购数据加载失败") : null
  };
}

export function useBatchPurchaseSnapshot(batch: Batch) {
  const batchId = batch.id;
  const scope = JSON.stringify([
    batchId,
    batch.version_ids.supplier,
    batch.files?.map(({ id, original_name, supplier_code }) => [id, original_name, supplier_code])
  ]);
  const enabled = batch.workflow === "self_operated_inbound" && batch.status === "succeeded";
  const [state, setState] = useState<SnapshotState>({
    scope,
    data: null,
    metadata: null,
    loading: enabled,
    error: null
  });
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const stop = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    window.clearTimeout(timer.current);
  }, []);
  const load = useCallback(
    (refresh: boolean) => {
      stop();
      const current = generation.current;
      const request = new AbortController();
      controller.current = request;
      const live = () => generation.current === current;
      let loaded: PurchaseSnapshot | null = null;
      setState((previous) => ({
        scope,
        data: previous.scope === scope ? previous.data : null,
        metadata: previous.scope === scope ? previous.metadata : null,
        loading: true,
        error: null
      }));
      const poll = async (initial: boolean) => {
        try {
          let reply = initial
            ? await beginPurchaseSnapshot(batchId, refresh, request.signal)
            : await getPurchaseSnapshot(batchId, request.signal);
          if (!live()) return;
          if (reply.state === "ready" && reply.snapshot_id !== loaded?.snapshot_id) {
            loaded = await readCompletePurchaseSnapshot(batchId, reply, request.signal);
            reply = loaded;
          }
          if (!live()) return;
          setState(receivedState(scope, reply, loaded));
          if (isPurchaseSnapshotActive(reply)) timer.current = window.setTimeout(() => void poll(false), 1500);
        } catch (error) {
          if (live())
            setState((previous) => ({
              ...previous,
              loading: false,
              error: error instanceof Error ? error.message : "读取整批采购数据失败，请重试"
            }));
        }
      };
      void poll(true);
    },
    [batchId, scope, stop]
  );
  useEffect(() => {
    if (enabled) load(false);
    return stop;
  }, [enabled, load, stop]);
  const current = state.scope === scope ? state : { scope, data: null, metadata: null, loading: enabled, error: null };
  const index = useMemo(() => {
    const result = new Map<string, PurchaseOption[]>();
    for (const row of current.data?.items ?? []) {
      const identity = purchaseIdentity(row.supplier_code, row.sku);
      const rows = result.get(identity) ?? [];
      rows.push(row);
      result.set(identity, rows);
    }
    return result;
  }, [current.data]);
  return { ...current, enabled, index, refresh: () => load(true) };
}
