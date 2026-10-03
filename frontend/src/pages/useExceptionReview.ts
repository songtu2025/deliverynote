import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api";
import type { DeliveryException } from "../types";
import { useDebouncedValue } from "../useDebouncedValue";

type ReviewScope = "unfinished" | "resolved" | "all";
type FilterField = "site" | "scale" | "stocking" | "reason";
type FilterValues = Partial<Record<FilterField, string>>;

export type ExceptionPage = {
  items: DeliveryException[];
  total: number;
  stats: {
    unfinished_count: number;
    unfinished_quantity: number;
    resolved_count: number;
    total_count: number;
  };
};

type ExceptionFilters = {
  reasons: string[];
  sites: string[];
  scales: string[];
  stocking: string[];
};

export function useExceptionReview(batchId: number, batchStatus?: string) {
  const [exceptions, setExceptions] = useState<DeliveryException[]>([]);
  const [exceptionTotal, setExceptionTotal] = useState(0);
  const [reviewPage, setReviewPage] = useState(1);
  const [reviewStats, setReviewStats] = useState({
    unfinishedCount: 0,
    unfinishedQuantity: 0,
    resolvedCount: 0,
    totalCount: 0
  });
  const [exceptionFilters, setExceptionFilters] = useState<ExceptionFilters>({
    reasons: [],
    sites: [],
    scales: [],
    stocking: []
  });
  const [exceptionsLoading, setExceptionsLoading] = useState(true);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [filterValues, setFilterValues] = useState<FilterValues>({});
  const [reviewScope, setReviewScope] = useState<ReviewScope>("unfinished");
  const pendingReviewDirection = useRef<"first" | "last" | null>(null);

  const fetchExceptionPage = useCallback(
    (requestedPage = reviewPage) => {
      const params = new URLSearchParams({
        offset: String((requestedPage - 1) * 10),
        limit: "10",
        review_scope: reviewScope
      });
      if (debouncedQuery.trim()) params.set("search", debouncedQuery.trim());
      if (filterValues.site) params.set("site", filterValues.site);
      if (filterValues.scale) params.set("scale_position", filterValues.scale);
      if (filterValues.stocking) params.set("stocking_position", filterValues.stocking);
      if (filterValues.reason) params.set("reason", filterValues.reason);
      return api<ExceptionPage>(`/api/batches/${batchId}/exceptions?${params}`);
    },
    [batchId, reviewPage, reviewScope, debouncedQuery, filterValues]
  );

  const applyExceptionPage = useCallback((result: ExceptionPage) => {
    setExceptions(result.items);
    setExceptionTotal(result.total);
    setReviewStats({
      unfinishedCount: result.stats.unfinished_count,
      unfinishedQuantity: result.stats.unfinished_quantity,
      resolvedCount: result.stats.resolved_count,
      totalCount: result.stats.total_count
    });
    if (!pendingReviewDirection.current) return undefined;
    const target =
      pendingReviewDirection.current === "first" ? (result.items[0] ?? null) : (result.items.at(-1) ?? null);
    pendingReviewDirection.current = null;
    return target;
  }, []);

  const changeScope = (scope: ReviewScope) => {
    setReviewPage(1);
    setReviewScope(scope);
  };

  const changeQuery = (value: string) => {
    setReviewPage(1);
    setQuery(value);
  };

  const changeFilter = (field: FilterField, value?: string) => {
    setReviewPage(1);
    setFilterValues((current) => ({ ...current, [field]: value }));
  };

  const queueReviewDirection = (direction: "first" | "last") => {
    pendingReviewDirection.current = direction;
  };

  const replaceException = (updated: DeliveryException) => {
    setExceptions((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  };

  useEffect(() => {
    void api<ExceptionFilters>(`/api/batches/${batchId}/exceptions/filters`)
      .then(setExceptionFilters)
      .catch(() => setExceptionFilters({ reasons: [], sites: [], scales: [], stocking: [] }));
  }, [batchId, batchStatus]);

  return {
    exceptions,
    exceptionTotal,
    reviewPage,
    setReviewPage,
    reviewStats,
    exceptionFilters,
    exceptionsLoading,
    setExceptionsLoading,
    query,
    reviewScope,
    siteFilter: filterValues.site,
    scaleFilter: filterValues.scale,
    stockingFilter: filterValues.stocking,
    reasonFilter: filterValues.reason,
    debouncedQuery,
    fetchExceptionPage,
    applyExceptionPage,
    changeScope,
    changeQuery,
    changeFilter,
    queueReviewDirection,
    replaceException
  };
}

export type ExceptionReview = ReturnType<typeof useExceptionReview>;
