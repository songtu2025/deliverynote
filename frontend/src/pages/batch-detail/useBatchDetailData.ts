import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api";
import { getBatchDetail } from "../../batchDetailApi";
import { getBatchInputVersions } from "../../batchListApi";
import type { Batch, DeliveryException, InputVersion } from "../../types";
import { useExceptionReview } from "./useExceptionReview";

export function useBatchDetailData(
  batchId: number,
  canRefreshSupplierVersion: boolean,
  setSplitTarget: (target: DeliveryException | null) => void
) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [activeSupplierVersion, setActiveSupplierVersion] = useState<InputVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loadRequestRef = useRef(0);
  const review = useExceptionReview(batchId, batch?.status);
  const { setExceptionsLoading, fetchExceptionPage, applyExceptionPage } = review;

  const handleLoadError = useCallback((error: unknown, silent: boolean, request: number) => {
    if (error instanceof ApiError && error.status === 401) {
      // 刷新遇到会话过期时终止后续成功提示，认证提示由应用统一处理。
      if (silent) throw error;
      return null;
    }
    if (request === loadRequestRef.current) {
      setLoadError(error instanceof Error ? error.message : "读取批次失败");
    }
    return null;
  }, []);

  const load = useCallback(
    async (silent = false) => {
      const request = ++loadRequestRef.current;
      if (!silent) {
        setLoading(true);
        setLoadError(null);
      }
      setExceptionsLoading(true);
      try {
        const batchRequest = getBatchDetail(batchId).then((result) => {
          if (request !== loadRequestRef.current) return;
          setBatch(result);
          if (!silent) setLoading(false);
        });
        const exceptionsRequest = fetchExceptionPage().then((result) => {
          if (request !== loadRequestRef.current) return result;
          const pendingTarget = applyExceptionPage(result);
          if (pendingTarget !== undefined) setSplitTarget(pendingTarget);
          return result;
        });
        const versionsRequest = canRefreshSupplierVersion
          ? getBatchInputVersions().then((versions) => {
              if (request !== loadRequestRef.current) return;
              setActiveSupplierVersion(
                versions.find((version) => version.kind === "supplier" && version.active) ?? null
              );
            })
          : Promise.resolve();
        const [, loadedPage] = await Promise.all([batchRequest, exceptionsRequest, versionsRequest]);
        if (request === loadRequestRef.current) setLoadError(null);
        return request === loadRequestRef.current ? loadedPage : null;
      } catch (error) {
        return handleLoadError(error, silent, request);
      } finally {
        if (request === loadRequestRef.current) {
          if (!silent) setLoading(false);
          setExceptionsLoading(false);
        }
      }
    },
    [
      batchId,
      canRefreshSupplierVersion,
      fetchExceptionPage,
      applyExceptionPage,
      setExceptionsLoading,
      setSplitTarget,
      handleLoadError
    ]
  );

  useEffect(() => {
    void load();
    return () => {
      loadRequestRef.current += 1;
    };
  }, [load]);

  return { batch, setBatch, activeSupplierVersion, loading, loadError, review, load };
}
export type BatchDetailData = ReturnType<typeof useBatchDetailData>;
