import type { ComponentProps } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PositionDraftRecords } from "./PositionDraftRecords";

type RecordsProps = ComponentProps<typeof PositionDraftRecords>;

function recordsProps(): RecordsProps {
  return {
    rowsState: {
      rows: [
        {
          id: 101,
          draft_id: 7,
          row_order: 1,
          store_site: "SEEKWAY:US",
          jiaji_sku: "演示 SKU",
          msku: "演示 MSKU",
          scale_position: "短尾",
          stocking_position: "备货",
          change_type: "unchanged",
          deleted: false,
          issues: []
        }
      ],
      rowsTotal: 45,
      rowsLoading: false,
      rowsError: null,
      search: "",
      setSearch: vi.fn(),
      site: "",
      setSite: vi.fn(),
      scale: "",
      setScale: vi.fn(),
      issueFilter: "all",
      setIssueFilter: vi.fn(),
      onlyModified: false,
      setOnlyModified: vi.fn(),
      page: 2,
      setPage: vi.fn(),
      pageSize: 20,
      setPageSize: vi.fn(),
      selectedRowIds: [],
      setSelectedRowIds: vi.fn(),
      refreshRows: vi.fn(),
      resetFilters: vi.fn(),
      hasActiveFilters: false
    },
    columns: [{ title: "积加 SKU", dataIndex: "jiaji_sku", key: "sku" }],
    disabled: false,
    bulkDeleting: false,
    bulkDeleteConfirmOpen: false,
    onNewRow: vi.fn(),
    onBulkDeleteOpenChange: vi.fn(),
    onBulkDeleteConfirm: vi.fn(async () => {})
  };
}

function recordsView(props: RecordsProps) {
  return (
    <ConfigProvider locale={zhCN}>
      <PositionDraftRecords {...props} />
    </ConfigProvider>
  );
}

describe("PositionDraftRecords", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("delegates filter changes and resets the page without owning filter state", async () => {
    const props = recordsProps();
    render(recordsView(props));

    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "演示 & SKU" } });
    fireEvent.change(screen.getByLabelText("站点筛选"), { target: { value: "SEEKWAY:CA" } });
    fireEvent.change(screen.getByLabelText("规模定位筛选"), { target: { value: "自定义定位" } });
    fireEvent.mouseDown(screen.getByLabelText("问题筛选"));
    fireEvent.click(await screen.findByText("仅错误"));
    fireEvent.click(screen.getByRole("checkbox", { name: "仅看已修改" }));

    expect(props.rowsState.setSearch).toHaveBeenCalledWith("演示 & SKU");
    expect(props.rowsState.setSite).toHaveBeenCalledWith("SEEKWAY:CA");
    expect(props.rowsState.setScale).toHaveBeenCalledWith("自定义定位");
    expect(props.rowsState.setIssueFilter).toHaveBeenCalledWith("errors");
    expect(props.rowsState.setOnlyModified).toHaveBeenCalledWith(true);
    expect(props.rowsState.setPage).toHaveBeenCalledTimes(5);
    expect(props.rowsState.setPage).toHaveBeenCalledWith(1);
    expect(screen.getByLabelText("搜索草稿")).toHaveValue("");
  });

  it("renders controlled filters and delegates reset and create actions", () => {
    const props = recordsProps();
    Object.assign(props.rowsState, {
      search: "演示",
      site: "SEEKWAY:US",
      scale: "短尾",
      onlyModified: true,
      hasActiveFilters: true
    });
    render(recordsView(props));

    expect(screen.getByLabelText("搜索草稿")).toHaveValue("演示");
    expect(screen.getByLabelText("站点筛选")).toHaveValue("SEEKWAY:US");
    expect(screen.getByLabelText("规模定位筛选")).toHaveValue("短尾");
    expect(screen.getByRole("checkbox", { name: "仅看已修改" })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "重置筛选" }));
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    expect(props.rowsState.resetFilters).toHaveBeenCalledOnce();
    expect(props.onNewRow).toHaveBeenCalledOnce();
  });

  it("keeps page navigation and page-size reset behavior", async () => {
    const props = recordsProps();
    render(recordsView(props));
    fireEvent.click(screen.getByTitle("3"));
    expect(props.rowsState.setPage).toHaveBeenLastCalledWith(3);
    expect(props.rowsState.setPageSize).toHaveBeenLastCalledWith(20);

    const selects = screen.getAllByRole("combobox");
    expect(selects).toHaveLength(2);
    fireEvent.mouseDown(selects[1]);
    fireEvent.click(await screen.findByText("50 条/页"));
    expect(props.rowsState.setPage).toHaveBeenLastCalledWith(1);
    expect(props.rowsState.setPageSize).toHaveBeenLastCalledWith(50);
  });

  it("uses row IDs for selection and displays the controlled selection count", () => {
    const props = recordsProps();
    const { rerender } = render(recordsView(props));
    const row = screen.getByText("演示 SKU").closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row!).getByRole("checkbox"));
    expect(props.rowsState.setSelectedRowIds).toHaveBeenCalledWith([101]);
    expect(screen.getByText("已选择 0 条")).toBeInTheDocument();
    props.rowsState.selectedRowIds = [101];
    rerender(recordsView(props));
    expect(screen.getByText("已选择 1 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批量删除（1）" })).toBeEnabled();
  });

  it("disables creation, selection and bulk deletion when the parent blocks writes", () => {
    const props = recordsProps();
    props.disabled = true;
    props.rowsState.selectedRowIds = [101];
    render(recordsView(props));
    expect(screen.getByRole("button", { name: "新增记录" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "批量删除（1）" })).toBeDisabled();
    const row = screen.getByText("演示 SKU").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row!).getByRole("checkbox")).toBeDisabled();
  });

  it.each([null, "演示读取失败"])("shows an empty or failed list without making requests: %s", (error) => {
    const props = recordsProps();
    Object.assign(props.rowsState, { rows: [], rowsTotal: 0, rowsError: error });
    render(recordsView(props));
    expect(screen.getByText(error ? "读取失败" : "草稿中没有符合条件的记录")).toBeInTheDocument();
    if (error) {
      expect(screen.getByText(error)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
      expect(props.rowsState.refreshRows).toHaveBeenCalledOnce();
    } else {
      expect(screen.queryByText("无法读取草稿记录")).not.toBeInTheDocument();
    }
  });

  it("delegates bulk confirmation to the parent without deleting rows locally", async () => {
    const props = recordsProps();
    props.rowsState.selectedRowIds = [101];
    props.bulkDeleteConfirmOpen = true;
    render(recordsView(props));
    await screen.findByText("删除选中的 1 条记录？");
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(props.onBulkDeleteConfirm).toHaveBeenCalledOnce());
    expect(screen.getByText("演示 SKU")).toBeInTheDocument();
    expect(props.rowsState.setSelectedRowIds).not.toHaveBeenCalled();
  });

  it("renders the pending bulk confirmation with cancellation disabled", async () => {
    const props = recordsProps();
    props.rowsState.selectedRowIds = [101];
    props.bulkDeleteConfirmOpen = true;
    const { rerender } = render(recordsView(props));
    await screen.findByText("删除选中的 1 条记录？");
    props.bulkDeleting = true;
    props.disabled = true;
    rerender(recordsView(props));
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeDisabled();
  });

  it("retains server totals and visible rows while reloading", () => {
    const props = recordsProps();
    props.rowsState.rowsLoading = true;
    render(recordsView(props));
    expect(screen.getByRole("table", { name: "库位草稿记录" })).toBeInTheDocument();
    expect(screen.getAllByText("共 45 条")).toHaveLength(2);
    expect(screen.getByText("演示 SKU")).toBeInTheDocument();
  });

  it("renders server text without interpreting HTML", () => {
    const props = recordsProps();
    const sku = '<img src=x onerror="window.__uiInjected=true">';
    props.rowsState.rows[0].jiaji_sku = sku;
    const { container } = render(recordsView(props));
    expect(screen.getByText(sku)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
