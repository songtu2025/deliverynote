import { useCallback, useEffect, useRef, useState } from "react";
import { App as AntApp } from "antd";
import { ApiError } from "../../api";
import { getBatchPage, getBatchInputVersions, getBatchOverreceiptRules } from "../../batchListApi";
import { getInboundSyncStatus } from "../../syncApi";
import { useDebouncedValue } from "../../useDebouncedValue";
import type {
  Batch,
  InputVersion,
  OverreceiptRuleVersion,
  SelfOperatedInboundSyncStatus,
  SelfOperatedOverreceiptRuleVersion
} from "../../types";
import type { BatchWorkflow } from "./batchWorkspace";

export function useBatchList(workflow: BatchWorkflow, active: boolean) {
  const { message } = AntApp.useApp();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchTotal, setBatchTotal] = useState(0);
  const [emptyDraftCount, setEmptyDraftCount] = useState(0);
  const [page, setPage] = useState(1);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [overreceiptRules, setOverreceiptRules] = useState<OverreceiptRuleVersion[]>([]);
  const [selfOperatedRules, setSelfOperatedRules] = useState<SelfOperatedOverreceiptRuleVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncStatus, setSyncStatus] = useState<SelfOperatedInboundSyncStatus | null>(null);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [statusFilter, setStatusFilter] = useState<string>();
  const loadedRef = useRef(false);
  const loadRequestRef = useRef(0);
  const refreshVersions = useCallback(async () => {
    const nextVersions = await getBatchInputVersions();
    setVersions(nextVersions);
    return nextVersions;
  }, []);

  const load = useCallback(
    async (background = false, knownInboundSyncStatus?: SelfOperatedInboundSyncStatus) => {
      const request = ++loadRequestRef.current;
      if (!background) setLoading(true);
      try {
        const [batchPage, versionRows, overreceiptRuleRows, inboundSyncStatus] = await Promise.all([
          getBatchPage(workflow, page, debouncedQuery, statusFilter),
          getBatchInputVersions(),
          getBatchOverreceiptRules(workflow),
          workflow === "self_operated_inbound"
            ? knownInboundSyncStatus
              ? Promise.resolve(knownInboundSyncStatus)
              : getInboundSyncStatus()
            : Promise.resolve(null)
        ]);
        if (request !== loadRequestRef.current) return;
        setBatches(batchPage.items);
        setBatchTotal(batchPage.total);
        setEmptyDraftCount(batchPage.empty_draft_count);
        setVersions(versionRows);
        if (workflow === "self_operated_inbound") {
          setSelfOperatedRules(overreceiptRuleRows as SelfOperatedOverreceiptRuleVersion[]);
          setSyncStatus(inboundSyncStatus);
        } else {
          setOverreceiptRules(overreceiptRuleRows as OverreceiptRuleVersion[]);
        }
      } catch (error) {
        if (request === loadRequestRef.current && !(error instanceof ApiError && error.status === 401)) {
          message.error(error instanceof Error ? error.message : "读取批次失败");
        }
      } finally {
        if (request === loadRequestRef.current) {
          loadedRef.current = true;
          if (!background) setLoading(false);
        }
      }
    },
    [page, debouncedQuery, statusFilter, workflow, message]
  );

  useEffect(() => {
    if (!loadedRef.current || active) void load(loadedRef.current);
  }, [active, load]);

  return {
    batches,
    batchTotal,
    emptyDraftCount,
    page,
    setPage,
    versions,
    overreceiptRules,
    selfOperatedRules,
    loading,
    initialized: loadedRef.current,
    query,
    setQuery,
    statusFilter,
    setStatusFilter,
    syncStatus,
    setSyncStatus,
    load,
    refreshVersions
  };
}
