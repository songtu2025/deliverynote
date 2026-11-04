import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReceiptReview from "./ReceiptReview";
import ReceiptRowActions from "./ReceiptRowActions";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import { createDetailBatch, fixtureJob } from "./detailFixtures";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";

const row: ReceiptRow = {
  file_id: 71,
  filename: "合成.xlsx",
  supplier: "合成供应商",
  sku: "SKU-A",
  original_site: "US",
  full_site: "",
  cumulative: 19,
  history: null,
  requested: null,
  issue: "产品信息站点不唯一",
  candidates: ["AMAZON:SEEKWAY:US", "AMAZON:OTHER:US"],
  delivery_numbers: [],
  order_numbers: [],
  purchase_numbers: [],
  item_ids: []
};
const batch = {
  ...createDetailBatch(),
  status: "draft",
  workflow: "self_operated_inbound" as const,
  jobs: {},
  receipt: { captured_at: "2026-11-04", issue_count: 1 }
};
const runAction = async (_name: string, operation: () => Promise<void>) => operation();
afterEach(() => vi.unstubAllGlobals());
function show(issue = row.issue, overrides: Partial<ReceiptRow> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init?: RequestInit) =>
      init?.method === "PUT"
        ? jsonResponse(batch)
        : jsonResponse({ items: [{ ...row, issue, ...overrides }], total: 1 })
    )
  );
  const load = vi.fn(async () => undefined);
  const onRefresh = vi.fn(async () => undefined);
  const onVersions = vi.fn();
  renderDetail(
    <ReceiptReview
      batch={batch}
      runAction={runAction}
      load={load}
      issuesOnly
      onRefresh={onRefresh}
      onVersions={onVersions}
    />
  );
  return { load, onRefresh, onVersions };
}
describe("计算前行内处理", () => {
  it("行级提醒沿用原因提供站点操作，历史显示未确认而不是待核对", async () => {
    show("", { reason: "产品信息站点不唯一", requested: 19, notice: "历史未确认，全部进入待处理" });
    expect(await screen.findByRole("combobox", { name: "选择站点" })).toBeEnabled();
    expect(screen.getByText("历史未确认，全部进入待处理")).toHaveClass("ant-typography-warning");
    expect(screen.getByText("未确认")).toBeInTheDocument();
  });
  it("站点选择使用原接口，保存后刷新并提示", async () => {
    const { load } = show();
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    await waitFor(() => expect(load).toHaveBeenCalledWith(true));
    const request = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "PUT");
    expect(request?.[0]).toBe("/api/batches/7/files/71/receipt-site");
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      sku: "SKU-A",
      original_site: "US",
      full_site: "AMAZON:OTHER:US"
    });
    expect(await screen.findByText("已保存该文件的站点选择，正在重新核对")).toBeInTheDocument();
  });
  it("未匹配商品跳转锁定资料，不调用不存在的版本更新接口", async () => {
    const { onVersions } = show("产品信息未匹配");
    fireEvent.click(await screen.findByRole("button", { name: "查看锁定资料" }));
    expect(onVersions).toHaveBeenCalled();
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });
  it("重新取数沿用页头确认文案，确认后才执行", async () => {
    const { onRefresh } = show("未找到自营仓入库单");
    fireEvent.click(await screen.findByRole("button", { name: "重新取数" }));
    expect(await screen.findByText("会清除当前计算与导出结果，再按本批单号获取最新历史。")).toBeInTheDocument();
    expect(onRefresh).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
  });
  it("其他原因仅查看明细并打开原抽屉", async () => {
    show("其他");
    fireEvent.click(await screen.findByRole("button", { name: "查看明细" }));
    expect(within(await screen.findByRole("dialog")).getByText("入库单：尚未确认")).toBeInTheDocument();
  });
  it("状态禁止选择时禁用并支持聚焦读取原因", async () => {
    renderDetail(
      <ReceiptRowActions
        row={row}
        disabledReason="当前批次状态不可预检"
        refreshing
        onChooseSite={vi.fn()}
        onOpen={vi.fn()}
      />
    );
    expect(screen.getByRole("combobox", { name: "选择站点" })).toBeDisabled();
    const target = screen.getByRole("combobox").closest(".ant-select")!.parentElement!;
    fireEvent.focus(target);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("当前批次状态不可预检");
  });
  it("导出运行中重新取数禁用", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ items: [{ ...row, issue: "供应商不一致" }], total: 1 }))
    );
    renderDetail(
      <ReceiptReview
        batch={{ ...batch, jobs: { export: fixtureJob({ kind: "export" }) } }}
        runAction={runAction}
        load={vi.fn()}
        issuesOnly
        onRefresh={vi.fn()}
      />
    );
    expect(await screen.findByRole("button", { name: "重新取数" })).toBeDisabled();
  });
});
