import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { deferred, jsonResponse } from "./admin/positionDraftTestSupport";

async function selectAllReviews() {
  fireEvent.click(screen.getByRole("radio", { name: /^全部 / }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("review_scope=all"), expect.anything())
  );
}

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
    expect(screen.getByText("2 个来源文件")).toBeInTheDocument();
    expect(screen.getByText(/^更新于/)).toBeInTheDocument();
  });

  it("未计算时仍默认待处理，保留全部标签和未知数量", async () => {
    state.batch.status = "draft";
    state.batch.summary = undefined;
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: "待处理 —" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "可导入 —" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "尚未计算" })).toBeInTheDocument();
    expect(screen.getByText("预检并计算后显示待处理")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "可导入 —" }));
    expect(screen.getByText("计算后显示可导入明细")).toBeVisible();
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
    expect(heading).toHaveTextContent("转自 自营仓 #1871 条 1 件、自营仓 #1882 条 3 件");
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
  });

  it("可入库标签在累计核对之前，计数使用接口行数", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const tab = await screen.findByRole("tab", { name: "可入库 2" });
    const names = screen.getAllByRole("tab").map((item) => item.textContent);
    expect(names.indexOf("可入库 2")).toBe(names.findIndex((name) => name?.startsWith("累计实收核对")) - 1);
    fireEvent.click(tab);
    expect(await screen.findByText("没有可入库记录")).toBeInTheDocument();
  });
  it("未计算时可入库显示未知数量与空状态", async () => {
    state.batch.status = "draft";
    state.batch.download_ready = false;
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "可入库 —" }));
    expect(screen.getByText("计算后显示可入库明细")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("import-rows"))).toBe(false);
  });

  it("待处理和已处理一次点击可达，保留搜索与全部审校筛选", async () => {
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: "待处理 4" })).toHaveAttribute("aria-selected", "true");
    fireEvent.change(screen.getByLabelText("搜索待处理记录"), { target: { value: "SKU" } });
    fireEvent.click(screen.getByRole("radio", { name: /^已处理 / }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("review_scope=resolved"), expect.anything())
    );
    fireEvent.click(screen.getByRole("tab", { name: /^累计实收核对/ }));
    fireEvent.click(screen.getByRole("tab", { name: "待处理 4" }));
    expect(screen.getByLabelText("搜索待处理记录")).toHaveValue("SKU");
    expect(container.querySelectorAll(".exception-review-card")).toHaveLength(1);
    await selectAllReviews();
  });

  it("来源文件和锁定资料在标签内，移除批次资料抽屉", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "来源文件 2" }));
    expect(screen.getByRole("columnheader", { name: "来源文件" })).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "锁定资料" }));
    expect(screen.getByText("purchase-v1")).toBeVisible();
    expect(screen.queryByRole("button", { name: "批次资料" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "批次资料" })).not.toBeInTheDocument();
  });

  it("筛选等待响应时保留表格和全批计数，不主动滚动", async () => {
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
      await screen.findByRole("tab", { name: "待处理 4" });
      const table = container.querySelector(".exception-review-card");
      await selectAllReviews();
      expect(container.querySelector(".exception-review-card")).toBe(table);
      expect(screen.getByLabelText("搜索待处理记录")).toBeVisible();
      expect(screen.getByRole("tab", { name: "待处理 4" })).toBeVisible();
      expect(scroll).not.toHaveBeenCalled();
      pending.resolve(undefined);
      await waitFor(() => expect(container.querySelectorAll(".exception-review-card .ant-table-row")).toHaveLength(5));
    } finally {
      pending.resolve(undefined);
      Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
    }
  });

  it("计算前保留五个标签，未知值为横线而非虚假零条", async () => {
    state.batch.status = "preflight_ready";
    state.batch.download_ready = false;
    state.batch.summary = undefined;
    state.exceptions = [];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: "待处理 0" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    expect(screen.queryByRole("tab", { name: /^已处理/ })).not.toBeInTheDocument();
    const summary = screen.getByLabelText("入库数量摘要");
    expect(within(summary).getAllByText("—")).toHaveLength(4);
    expect(screen.queryByText("计算后生成")).not.toBeInTheDocument();
    expect(screen.queryByText("没有待处理，可以直接生成结果")).not.toBeInTheDocument();
  });
  it("调整草稿时仅突出按调整重算，放弃后恢复页头主操作", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const header = await screen.findByRole("region", { name: "批次任务状态" });
    const generate = within(header).getByRole("button", { name: "生成结果" });
    expect(generate).toHaveClass("ant-btn-primary");
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    expect(screen.getByRole("button", { name: "按调整重算（1 处）" })).toHaveClass("ant-btn-primary");
    expect(generate).toHaveClass("ant-btn-default");
    expect(header.querySelector(".ant-btn-primary")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(generate).toHaveClass("ant-btn-primary");
  });

  it("已处理分段显示完成记录，数量保持全批口径", async () => {
    state.exceptions.push({ ...state.exceptions[0], id: 99, sku: "SKU-已处理", status: "resolved" });
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: "已处理 1" }));
    expect(await screen.findByRole("button", { name: "SKU-已处理" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "SKU-A" })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "全部 5" })).toBeInTheDocument();
  });
});
