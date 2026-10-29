import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { jsonResponse } from "./admin/positionDraftTestSupport";

describe("自营仓详情标签工作区", () => {
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

  it("计算后默认展示审校，直接切换状态并保留筛选", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const reviewTab = await screen.findByRole("tab", { name: /待处理审校/ });
    expect(reviewTab).toHaveAttribute("aria-selected", "true");
    fireEvent.click(await screen.findByRole("button", { name: /已处理 \d+ 条/ }));
    fireEvent.click(screen.getByRole("tab", { name: /累计实收核对/ }));
    expect(screen.getByRole("tab", { name: /累计实收核对/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(reviewTab);
    expect(await screen.findByRole("button", { name: /已处理 \d+ 条/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("tab", { name: /业务文件/ }));
    expect(await screen.findByRole("columnheader", { name: "来源文件" })).toBeInTheDocument();
  });

  it("预检后默认核对，待处理明确显示计算后生成", async () => {
    state.batch.status = "preflight_ready";
    state.batch.download_ready = false;
    state.batch.summary = undefined;
    state.exceptions = [];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: /累计实收核对/ })).toHaveAttribute("aria-selected", "true");
    const task = screen.getByRole("region", { name: "当前批次任务" });
    expect(within(task).getByText("计算后生成")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /待处理审校/ }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("启动计算后生成待处理明细");
    expect(screen.queryByText("本批次没有待处理记录")).not.toBeInTheDocument();
  });

  it("未预检默认文件，锁定版本可以直接打开", async () => {
    state.batch.status = "draft";
    state.batch.download_ready = false;
    delete state.batch.receipt;
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: /业务文件/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "锁定版本" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("purchase-v1");
  });

  it("后台刷新不切走用户选择，处理异常按钮打开审校面板", async () => {
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: /锁定版本/ }));
    const scroll = vi.fn();
    Object.defineProperty(container.querySelector(".review-section-anchor"), "scrollIntoView", { value: scroll });
    fireEvent.click(await screen.findByRole("button", { name: "处理异常" }));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /待处理审校/ })).toHaveAttribute("aria-selected", "true")
    );
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(document.activeElement).toHaveClass("review-section-anchor");
  });
});
