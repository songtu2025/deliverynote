import { useContext, useEffect, useState } from "react";
import { getInboundAllocations, purchaseIdentity } from "../../inboundExceptionApi";
import { PurchaseSnapshotContext } from "./useBatchPurchaseSnapshot";

function useDetailSection<T>(exceptionId: number, load: (id: number) => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ id: number; data: T | null; loading: boolean; error: string | null }>({
    id: exceptionId,
    data: null,
    loading: true,
    error: null
  });
  useEffect(() => {
    let cancelled = false;
    setState({ id: exceptionId, data: null, loading: true, error: null });
    void load(exceptionId).then(
      (data) => {
        if (!cancelled) setState({ id: exceptionId, data, loading: false, error: null });
      },
      (failure: unknown) => {
        if (!cancelled)
          setState({
            id: exceptionId,
            data: null,
            loading: false,
            error: failure instanceof Error ? failure.message : "读取失败，请重试"
          });
      }
    );
    return () => {
      cancelled = true;
    };
  }, [exceptionId, load, attempt]);
  const current = state.id === exceptionId ? state : { data: null, loading: true, error: null };
  return { ...current, retry: () => setAttempt((value) => value + 1) };
}

export function useInboundExceptionDetails(exceptionId: number, supplierCode: string, sku: string) {
  const snapshot = useContext(PurchaseSnapshotContext);
  if (!snapshot) throw new Error("采购明细需要批次快照上下文");
  const purchases = {
    data: snapshot.data
      ? { queried_at: snapshot.data.completed_at, items: snapshot.index.get(purchaseIdentity(supplierCode, sku)) ?? [] }
      : null,
    loading: snapshot.loading,
    error: snapshot.loading || snapshot.data ? null : (snapshot.error ?? "请在批次审校区域加载整批采购数据")
  };
  return {
    purchases,
    allocations: useDetailSection(exceptionId, getInboundAllocations)
  };
}
