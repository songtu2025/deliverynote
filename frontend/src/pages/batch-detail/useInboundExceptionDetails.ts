import { useEffect, useState } from "react";
import { getInboundAllocations, getPurchaseOptions } from "../../inboundExceptionApi";

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

export function useInboundExceptionDetails(exceptionId: number) {
  return {
    purchases: useDetailSection(exceptionId, getPurchaseOptions),
    allocations: useDetailSection(exceptionId, getInboundAllocations)
  };
}
