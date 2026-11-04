import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { deferred, jsonResponse } from "./admin/positionDraftTestSupport";

describe("交货批次详情标签页", () => {
  const { state } = setupBatchDetailTest();

  it("计算后默认显示待处理，数量条按汇总显示两段", async () => {
    state.exceptions = [state.exceptions[0]];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: "待处理 1" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("tab", { name: "可导入 2" })).toBeInTheDocument();
    const bar = screen.getByRole("img", { name: "可导入 100，待处理 60" });
    expect(bar.children).toHaveLength(2);
    expect(screen.getByText("交货 160 = 可导入 100 + 待处理 60")).toHaveClass("conservation-ok");
    expect(screen.getByText(/2 个来源文件，更新于/)).toBeInTheDocument();
  });

  it("未计算时默认来源文件且不显示数量条和待处理标签", async () => {
    state.batch.status = "draft";
    state.batch.summary = undefined;
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: "来源文件 2" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: /^待处理/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /^可导入/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /^可导入/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "锁定资料" }));
    expect(screen.getByText("purchase-v1")).toBeVisible();
  });

  it("开始审校先切换标签再滚动聚焦，返回标签保留选择", async () => {
    state.exceptions = [state.exceptions[0]];
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
    try {
      renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      fireEvent.click(await screen.findByRole("tab", { name: "来源文件 2" }));
      fireEvent.click(screen.getByRole("button", { name: "开始审校" }));
      await waitFor(() =>
        expect(screen.getByRole("tab", { name: "待处理 1" })).toHaveAttribute("aria-selected", "true")
      );
      await waitFor(() => expect(document.activeElement).toHaveClass("review-section-anchor"));
      expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
      fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
      expect(screen.getByRole("tab", { name: "来源文件 2" })).toHaveAttribute("aria-selected", "true");
    } finally {
      Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
    }
  });

  it("全部可扣时仍可从标签页查看明细", async () => {
    state.batch.summary = { delivery_total: 1, import_total: 1, manual_total: 0, conserved: true };
    state.exceptions = [];
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("/import-rows?")
          ? Promise.resolve(
              jsonResponse({
                items: [
                  {
                    file_id: 10,
                    file_name: "合成文件.xlsx",
                    row_index: 0,
                    sku: "SKU-可导入",
                    site: "US",
                    warehouse: "本地仓",
                    supplier_code: "GYS-001",
                    quantity: 1,
                    document_note: "",
                    delivery_note: ""
                  }
                ],
                total: 1
              })
            )
          : originalFetch(input, init)
      )
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "可导入 1" }));
    expect(await screen.findByText("SKU-可导入")).toBeVisible();
  });

  it("转交来源显示汇总、跳转及对应文件标注", async () => {
    state.batch.transfer_sources = [
      { batch_id: 187, batch_name: "来源一", record_count: 1, quantity: 1, file_ids: [10] },
      { batch_id: 188, batch_name: "来源二", record_count: 2, quantity: 3, file_ids: [10] }
    ];
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByRole("tab", { name: "可导入 2" });
    const heading = container.querySelector(".batch-heading")!;
    expect(heading).toHaveTextContent("转自 自营仓 #187 · 1 条 1 件、自营仓 #188 · 2 条 3 件");
    expect(within(heading as HTMLElement).getByRole("link", { name: "#187" })).toHaveAttribute(
      "href",
      "/self-operated/187"
    );
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
    const firstFile = screen.getByText("KuangBiao-A交货单.xlsx").closest("tr")!;
    expect(firstFile).toHaveTextContent("转自 #187、转自 #188");
    expect(within(firstFile).getByRole("link", { name: "#188" })).toHaveAttribute("href", "/self-operated/188");
    expect(screen.getByText("KuangBiao-B交货单.xlsx").closest("tr")).not.toHaveTextContent("转自");
  });

  it("没有转交来源时不显示来源文字", async () => {
    state.batch.transfer_sources = [];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByRole("tab", { name: "可导入 2" });
    expect(screen.queryByText(/转自/)).not.toBeInTheDocument();
  });

  it("读取审校统计失败时仅显示两段待处理数量", async () => {
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("/exceptions?")
          ? Promise.resolve(new Response("读取失败", { status: 500 }))
          : originalFetch(input, init)
      )
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText("读取批次失败");
    expect(screen.getByRole("img", { name: "可导入 100，待处理 60" }).children).toHaveLength(2);
    expect(screen.queryByText("保留待处理")).not.toBeInTheDocument();
  });
});

describe("自营仓详情工作区", () => {
  const { state } = setupBatchDetailTest();

  beforeEach(() => {
    state.batch.workflow = "self_operated_inbound";
    state.batch.receipt = {
      cumulative_total: 163,
      history_total: 3,
      requested_total: 160,
      issue_count: 0,
      captured_at: "2026-10-29T00:00:00Z"
    };
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("/receipts?")
          ? Promise.resolve(jsonResponse({ items: [], total: 0 }))
          : originalFetch(input, init)
      )
    );
  });

  it("状态一次点击可达，共用审校表格且保留搜索", async () => {
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("radio", { name: "未完成（4）" })).toBeChecked();
    expect(screen.queryByRole("region", { name: "审校概览" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "开始审校" })).not.toBeInTheDocument();
    const reviewCard = container.querySelector(".exception-review-card");
    fireEvent.click(screen.getByRole("radio", { name: /^已处理/ }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("review_scope=resolved"), expect.anything())
    );
    expect(container.querySelector(".exception-review-card")).toBe(reviewCard);
    fireEvent.change(screen.getByLabelText("搜索待处理记录"), { target: { value: "SKU" } });
    fireEvent.click(screen.getByRole("radio", { name: "累计实收核对" }));
    fireEvent.click(screen.getByRole("radio", { name: /^已处理/ }));
    expect(screen.getByLabelText("搜索待处理记录")).toHaveValue("SKU");
    expect(container.querySelectorAll(".exception-review-card")).toHaveLength(1);
    fireEvent.click(screen.getByRole("radio", { name: /^全部审校/ }));
    expect(screen.getByRole("radio", { name: /^全部审校/ })).toBeChecked();
    expect(container.querySelector(".exception-review-card")).toBe(reviewCard);
  });

  it("文件与锁定版本集中到资料抽屉，关闭后保留当前视图", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: /^已处理/ }));
    fireEvent.click(screen.getByRole("button", { name: "批次资料" }));
    const drawer = within(screen.getByRole("dialog", { name: "批次资料" }));
    expect(drawer.getByRole("columnheader", { name: "来源文件" })).toBeInTheDocument();
    expect(drawer.getByText("purchase-v1")).toBeInTheDocument();
    fireEvent.click(drawer.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("radio", { name: /^已处理/ })).toBeChecked();
    expect(screen.queryByRole("radio", { name: "业务文件" })).not.toBeInTheDocument();
  });

  it("切换状态等待响应时保留表格、筛选和计数，不主动滚动页面", async () => {
    state.exceptions.push({ ...state.exceptions[0], id: 35, sku: "SKU-已处理", status: "resolved" });
    const pending = deferred<void>();
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("review_scope=all")
          ? pending.promise.then(() => originalFetch(input, init))
          : originalFetch(input, init)
      )
    );
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
    try {
      const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      await screen.findByRole("radio", { name: "未完成（4）" });
      fireEvent.click(screen.getByRole("radio", { name: /^全部审校/ }));
      await waitFor(() =>
        expect(fetch).toHaveBeenCalledWith(expect.stringContaining("review_scope=all"), expect.anything())
      );
      expect(screen.getByLabelText("搜索待处理记录")).toBeVisible();
      expect(screen.getByRole("columnheader", { name: "SKU" })).toBeVisible();
      expect(screen.getByText("未完成（4）")).toBeVisible();
      expect(scroll).not.toHaveBeenCalled();
      pending.resolve(undefined);
      await waitFor(() => expect(container.querySelectorAll(".exception-review-card .ant-table-row")).toHaveLength(5));
    } finally {
      pending.resolve(undefined);
      Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
    }
  });

  it("未计算时直接显示文件准备和核对，不显示虚假的零条审校", async () => {
    state.batch.status = "preflight_ready";
    state.batch.download_ready = false;
    state.batch.summary = undefined;
    state.exceptions = [];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("columnheader", { name: "来源文件" })).toBeInTheDocument();
    expect(screen.getByText("累计实收核对")).toBeInTheDocument();
    expect(within(screen.getByLabelText("入库数量摘要")).getByText("计算后生成")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.queryByText("没有待处理，可以直接生成结果")).not.toBeInTheDocument();
  });
});
