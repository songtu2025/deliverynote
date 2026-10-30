import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { jsonResponse } from "./admin/positionDraftTestSupport";

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
    expect(await screen.findByRole("tab", { name: "未完成（4）" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("region", { name: "审校概览" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /^已处理/ }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("review_scope=resolved"), expect.anything())
    );
    fireEvent.change(screen.getByLabelText("搜索待处理记录"), { target: { value: "SKU" } });
    fireEvent.click(screen.getByRole("tab", { name: "累计实收核对" }));
    fireEvent.click(screen.getByRole("tab", { name: /^已处理/ }));
    expect(screen.getByLabelText("搜索待处理记录")).toHaveValue("SKU");
    expect(container.querySelectorAll(".exception-review-card")).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: /^全部审校/ }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(expect.stringContaining("review_scope=all"), expect.anything())
    );
  });

  it("文件与锁定版本集中到资料抽屉，关闭后保留当前视图", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: /^已处理/ }));
    fireEvent.click(screen.getByRole("button", { name: "批次资料" }));
    const drawer = within(screen.getByRole("dialog", { name: "批次资料" }));
    expect(drawer.getByRole("columnheader", { name: "来源文件" })).toBeInTheDocument();
    expect(drawer.getByText("purchase-v1")).toBeInTheDocument();
    fireEvent.click(drawer.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("tab", { name: /^已处理/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "业务文件" })).not.toBeInTheDocument();
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
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByText("本批次没有待处理记录")).not.toBeInTheDocument();
  });

  it("处理异常直接选择未完成并聚焦表格", async () => {
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
    try {
      const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      fireEvent.click(await screen.findByRole("tab", { name: /^已处理/ }));
      fireEvent.click(screen.getByRole("tab", { name: "累计实收核对" }));
      fireEvent.click(screen.getByRole("button", { name: "处理异常" }));
      await waitFor(() =>
        expect(screen.getByRole("tab", { name: /^未完成/ })).toHaveAttribute("aria-selected", "true")
      );
      await waitFor(() => expect(document.activeElement).toBe(container.querySelector(".review-section-anchor")));
      expect(scroll).toHaveBeenCalled();
    } finally {
      Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
    }
  });
});
