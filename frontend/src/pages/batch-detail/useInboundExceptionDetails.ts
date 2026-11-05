import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { getInboundAllocations, purchaseIdentity } from "../../inboundExceptionApi";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";

function useDetailSection<T>(exceptionId: number, load: (id: number) => Promise<T>) {
  const generation = useRef(0);
  const [state, setState] = useState<{ id: number; data: T | null; loading: boolean; error: string | null }>({
    id: exceptionId,
    data: null,
    loading: true,
    error: null
  });
  const reload = useCallback(async () => {
    const request = ++generation.current;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const data = await load(exceptionId);
      if (request !== generation.current) return null;
      setState({ id: exceptionId, data, loading: false, error: null });
      return data;
    } catch (failure) {
      if (request === generation.current)
        setState((previous) => ({
          ...previous,
          loading: false,
          error: failure instanceof Error ? failure.message : "读取失败，请重试"
        }));
      return null;
    }
  }, [exceptionId, load]);
  useEffect(() => {
    void reload();
    return () => {
      generation.current += 1;
    };
  }, [reload]);
  const current = state.id === exceptionId ? state : { data: null, loading: true, error: null };
  return { ...current, reload, retry: () => void reload() };
}

export function useInboundExceptionDetails(
  exceptionId: number,
  supplierCode: string,
  sku: string,
  identity?: { batch_file_id: number; full_site: string }
) {
  const snapshot = useContext(PurchaseSnapshotContext);
  if (!snapshot) throw new Error("采购明细需要批次快照上下文");
  const purchases = {
    data: snapshot.data
      ? { queried_at: snapshot.data.completed_at, items: snapshot.index.get(purchaseIdentity(supplierCode, sku)) ?? [] }
      : null,
    loading: snapshot.loading,
    error: snapshot.loading || snapshot.data ? null : (snapshot.error ?? "请在批次审校区域加载整批采购数据")
  };
  const fileId = identity?.batch_file_id;
  const site = identity?.full_site ?? "";
  const loadAllocations = useCallback(
    (id: number) =>
      getInboundAllocations(id, fileId === undefined ? undefined : { batch_file_id: fileId, sku, full_site: site }),
    [fileId, sku, site]
  );
  return {
    purchases,
    allocations: useDetailSection(exceptionId, loadAllocations)
  };
}
