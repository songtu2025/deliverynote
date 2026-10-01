import type { ComponentProps } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { INPUT_KIND_BY_VALUE } from "./adminConstants";
import type { InputKind } from "./adminConstants";
import { InputVersionPreviewPanel } from "./InputVersionPreviewPanel";

type PreviewProps = ComponentProps<typeof InputVersionPreviewPanel>;

function previewProps(kind: InputKind = "product"): PreviewProps {
  const columns = ["SKU", "数量", "已锁定", "需复核", "说明"];
  return {
    kind,
    label: INPUT_KIND_BY_VALUE[kind].label,
    activeVersion: {
      id: 1,
      kind,
      name: "synthetic-preview",
      original_name: "synthetic-preview.xlsx",
      active: true,
      created_by: 1,
      created_at: "2026-07-21T09:00:00Z"
    },
    inspection: {
      summary: { kind, row_count: 123, columns, metrics: {}, issues: [] },
      preview: {
        kind,
        columns,
        rows: [{ SKU: "SYNTHETIC-SKU", 数量: 0, 已锁定: true, 需复核: false, 说明: null }],
        total: 123,
        offset: 0,
        limit: 20
      }
    },
    loading: false,
    inspectionLoading: false,
    inspectionError: null,
    onRetry: vi.fn()
  };
}

function previewView(props: PreviewProps) {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { motion: false } }}>
      <InputVersionPreviewPanel {...props} />
    </ConfigProvider>
  );
}

describe("InputVersionPreviewPanel", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("uses the server's columns and total while preserving zero, booleans and nulls", () => {
    render(previewView(previewProps()));
    const table = screen.getByRole("table", { name: "商品信息数据预览" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent)
    ).toEqual(["Excel 行", "SKU", "数量", "已锁定", "需复核", "说明"]);
    const row = within(table).getAllByRole("row")[1];
    for (const text of ["2", "SYNTHETIC-SKU", "0", "是", "否", "—"]) {
      expect(within(row).getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText("当前展示前 1 行，共 123 行 · 5 个字段")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByTitle("2")).not.toBeInTheDocument();
  });

  it("keeps source row order and adds the server offset to Excel row numbers without mutating data", () => {
    const props = previewProps();
    const inspection = props.inspection!;
    inspection.preview.offset = 20;
    inspection.preview.rows.push({ SKU: "NEXT-SKU", 数量: 12.5, 已锁定: false, 需复核: true, 说明: "" });
    const original = structuredClone(inspection);
    render(previewView(props));
    const rows = within(screen.getByRole("table", { name: "商品信息数据预览" }))
      .getAllByRole("row")
      .slice(1);
    expect(rows.map((row) => row.querySelector("td")?.textContent)).toEqual(["22", "23"]);
    expect(rows.map((row) => row.querySelectorAll("td")[1]?.textContent)).toEqual(["SYNTHETIC-SKU", "NEXT-SKU"]);
    expect(within(rows[1]).getByText("12.5")).toBeInTheDocument();
    expect(inspection).toEqual(original);
  });

  it.each(["versions", "inspection", "waiting"])("renders the controlled %s loading state", (state) => {
    const props = previewProps();
    if (state === "versions") props.loading = true;
    if (state === "inspection") props.inspectionLoading = true;
    if (state === "waiting") props.inspection = null;
    render(previewView(props));
    expect(screen.getByText(state === "versions" ? "读取资料状态" : "读取摘要与预览")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("distinguishes an inactive version from an active version with empty preview data", () => {
    const props = previewProps();
    props.activeVersion = null;
    props.inspection = null;
    const { rerender } = render(previewView(props));
    expect(screen.getByText("商品信息尚无启用版本")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const activeProps = previewProps();
    activeProps.inspection!.preview.rows = [];
    activeProps.inspection!.preview.total = 0;
    activeProps.inspection!.summary.row_count = 0;
    rerender(previewView(activeProps));
    expect(screen.getByText("当前版本没有可预览的数据")).toBeInTheDocument();
    expect(screen.getByText("当前展示前 0 行，共 0 行 · 5 个字段")).toBeInTheDocument();
  });

  it("delegates retry without fetching or clearing the parent's error locally", () => {
    const props = previewProps();
    props.inspection = null;
    props.inspectionError = { versionId: 1, message: "合成读取失败" };
    render(previewView(props));
    expect(screen.getByText("无法读取当前版本内容")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(props.onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByText("合成读取失败")).toBeInTheDocument();
  });

  it("does not display an error belonging to a different active version", () => {
    const props = previewProps();
    props.inspectionError = { versionId: 2, message: "其他版本失败" };
    render(previewView(props));
    expect(screen.getByText("SYNTHETIC-SKU")).toBeInTheDocument();
    expect(screen.queryByText("其他版本失败")).not.toBeInTheDocument();
  });

  it.each(["position", "supplier"] as const)("uses %s metrics from the inspection, with zero fallbacks", (kind) => {
    const props = previewProps(kind);
    props.inspection!.summary.metrics = kind === "position" ? { sites: 15, skus: 4410 } : { aliases: 7 };
    render(previewView(props));
    const metrics =
      kind === "position" ? ["15 个站点", "4410 个积加 SKU", "0 个 MSKU"] : ["7 个别名", "0 个供应商已配置别名"];
    for (const text of metrics) expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: `${props.label}数据预览` })).toBeInTheDocument();
  });

  it("updates the accessible name and columns when the parent switches input kind", () => {
    const { rerender } = render(previewView(previewProps()));
    const supplierProps = previewProps("supplier");
    supplierProps.inspection!.preview.columns = ["供应商名称"];
    supplierProps.inspection!.preview.rows = [{ 供应商名称: "SYNTHETIC-SUPPLIER" }];
    rerender(previewView(supplierProps));
    const table = screen.getByRole("table", { name: "供应商资料数据预览" });
    expect(within(table).getByText("SYNTHETIC-SUPPLIER")).toBeInTheDocument();
    expect(within(table).queryByText("SYNTHETIC-SKU")).not.toBeInTheDocument();
  });

  it("renders user-provided HTML characters as text in headers and cells", () => {
    const props = previewProps();
    const header = "<b>合成字段</b>";
    const value = '<img src=x onerror="window.__uiInjected=true">';
    props.inspection!.preview.columns = [header];
    props.inspection!.preview.rows = [{ [header]: value }];
    const { container } = render(previewView(props));
    expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    expect(screen.getByText(value)).toBeInTheDocument();
    expect(container.querySelector("img, b")).toBeNull();
  });
});
