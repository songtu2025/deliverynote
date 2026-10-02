import { useEffect, useState } from "react";

import { ApiError } from "../../api";
import type { PositionDraftRow } from "../../types";
import { useDebouncedValue } from "../../useDebouncedValue";
import { listRows } from "./positionDraftApi";

export function usePositionDraftRows(draftId?: number) {
  const [rows, setRows] = useState<PositionDraftRow[]>([]);
  const [rowsTotal, setRowsTotal] = useState(0);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [site, setSite] = useState("");
  const [scale, setScale] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const debouncedSite = useDebouncedValue(site);
  const debouncedScale = useDebouncedValue(scale);
  const [issueFilter, setIssueFilter] = useState<"all" | "errors">("all");
  const [onlyModified, setOnlyModified] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [refreshRowsKey, setRefreshRowsKey] = useState(0);
  const [selectedRowIds, setSelectedRowIds] = useState<number[]>([]);

  useEffect(() => {
    if (draftId === undefined) return;
    let active = true;
    setRowsLoading(true);
    setRowsError(null);
    void listRows(draftId, {
      offset: (page - 1) * pageSize,
      limit: pageSize,
      search: debouncedSearch,
      site: debouncedSite,
      scale_position: debouncedScale,
      only_errors: issueFilter === "errors",
      only_modified: onlyModified
    })
      .then((result) => {
        if (!active) return;
        setRows(result.rows);
        setRowsTotal(result.total);
        setSelectedRowIds((current) => current.filter((id) => result.rows.some((row) => row.id === id)));
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof ApiError && error.status === 401)) return;
        setRows([]);
        setRowsTotal(0);
        setRowsError(error instanceof Error ? error.message : "读取草稿记录失败");
      })
      .finally(() => {
        if (active) setRowsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    debouncedScale,
    debouncedSearch,
    debouncedSite,
    draftId,
    issueFilter,
    onlyModified,
    page,
    pageSize,
    refreshRowsKey
  ]);

  const refreshRows = () => setRefreshRowsKey((value) => value + 1);

  const resetFilters = () => {
    setSearch("");
    setSite("");
    setScale("");
    setIssueFilter("all");
    setOnlyModified(false);
    setPage(1);
  };

  return {
    rows,
    rowsTotal,
    rowsLoading,
    rowsError,
    search,
    setSearch,
    site,
    setSite,
    scale,
    setScale,
    issueFilter,
    setIssueFilter,
    onlyModified,
    setOnlyModified,
    page,
    setPage,
    pageSize,
    setPageSize,
    selectedRowIds,
    setSelectedRowIds,
    refreshRows,
    resetFilters,
    hasActiveFilters: Boolean(search.trim() || site.trim() || scale.trim() || issueFilter !== "all" || onlyModified)
  };
}
