import { useCallback, useEffect, useRef, useState } from "react";
import { App as AntApp } from "antd";
import { ApiError } from "../../api";
import { getOverreceiptRules, getRuleWarehouses } from "../../overreceiptRuleApi";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "../../types";

export function useRulesData(active: boolean) {
  const { message } = AntApp.useApp();
  const [rules, setRules] = useState<OverreceiptRuleVersion[]>([]);
  const [selfOperatedRules, setSelfOperatedRules] = useState<SelfOperatedOverreceiptRuleVersion[]>([]);
  const [warehouses, setWarehouses] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [warehousesLoading, setWarehousesLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);
  const loadRequestRef = useRef(0);
  const sessionRef = useRef(0);
  const warehouseRequestRef = useRef(0);
  const warehousesLoadedRef = useRef(false);
  const warehousesPendingRef = useRef(false);

  const beginOperation = useCallback(() => {
    const session = sessionRef.current;
    return () => session === sessionRef.current;
  }, []);

  const invalidateRuleRead = () => {
    loadRequestRef.current += 1;
    setLoading(false);
  };

  const handleLoadError = useCallback((loadError: unknown, afterWrite: boolean, requestId: number) => {
    if (requestId !== loadRequestRef.current) return false;
    if (loadError instanceof ApiError && loadError.status === 401) {
      if (afterWrite) throw loadError;
      return false;
    }
    const detail = loadError instanceof Error ? loadError.message : "读取超收规则失败";
    setError(`${afterWrite ? "变更已保存，但读取超收规则失败：" : ""}${detail}`);
    return false;
  }, []);

  const load = useCallback(
    async (background = false, afterWrite = false) => {
      const requestId = ++loadRequestRef.current;
      if (!background) setLoading(true);
      setError(null);
      try {
        const [ruleRows, selfOperatedRuleRows] = await Promise.all([
          getOverreceiptRules("delivery"),
          getOverreceiptRules("self_operated_inbound")
        ]);
        if (requestId !== loadRequestRef.current) return false;
        setRules(ruleRows);
        setSelfOperatedRules(selfOperatedRuleRows);
        return true;
      } catch (loadError) {
        return handleLoadError(loadError, afterWrite, requestId);
      } finally {
        if (requestId === loadRequestRef.current) {
          loadedRef.current = true;
          setLoading(false);
        }
      }
    },
    [handleLoadError]
  );

  const loadWarehouses = useCallback(async () => {
    if (warehousesLoadedRef.current || warehousesPendingRef.current) return;
    const requestId = ++warehouseRequestRef.current;
    warehousesPendingRef.current = true;
    setWarehousesLoading(true);
    try {
      const rows = await getRuleWarehouses();
      if (requestId !== warehouseRequestRef.current) return;
      setWarehouses(rows);
      warehousesLoadedRef.current = true;
    } catch (loadError) {
      if (requestId !== warehouseRequestRef.current) return;
      if (loadError instanceof ApiError && loadError.status === 401) return;
      message.error(loadError instanceof Error ? loadError.message : "读取仓库选项失败");
    } finally {
      if (requestId === warehouseRequestRef.current) {
        warehousesPendingRef.current = false;
        setWarehousesLoading(false);
      }
    }
  }, [message]);

  const refresh = () => {
    warehouseRequestRef.current += 1;
    warehousesPendingRef.current = false;
    warehousesLoadedRef.current = false;
    setWarehouses([]);
    setWarehousesLoading(false);
    void load();
  };

  useEffect(() => {
    warehousesPendingRef.current = false;
    setWarehousesLoading(false);
    if (!loadedRef.current || active) void load(loadedRef.current);
    return () => {
      sessionRef.current += 1;
      loadRequestRef.current += 1;
      warehouseRequestRef.current += 1;
    };
  }, [active, load]);

  return {
    rules,
    setRules,
    selfOperatedRules,
    setSelfOperatedRules,
    warehouses,
    loading,
    warehousesLoading,
    error,
    load,
    loadWarehouses,
    refresh,
    beginOperation,
    invalidateRuleRead
  };
}
export type RulesData = ReturnType<typeof useRulesData>;
