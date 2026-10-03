import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupBatchesPageTests, jsonResponse } from "./batchesPageTestSupport";
import BatchesPage from "./BatchesPage";

describe("BatchesPageInboundSync", () => {
  const state = setupBatchesPageTests();
  it("shows the independent self-operated inbound workspace", async () => {
    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: AntApp });

    await screen.findByRole("heading", { name: "自营仓入库" });
    const status = await screen.findByRole("region", { name: "运行状态" });
    expect(within(status).getByText("4 / 4 已就绪")).toBeInTheDocument();
    expect(within(status).getByText("待入库数据")).toBeInTheDocument();
    expect(screen.getByText("待入库 + 部分入库")).toBeInTheDocument();
    expect(screen.getByText("数据已启用")).toBeInTheDocument();
    expect(screen.queryByText("候选剩余应收总量")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看同步详情" }));
    expect(screen.getByText("候选剩余应收总量")).toBeInTheDocument();
    expect(screen.getByText(/包含 2 条“共享”站点数据/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载提醒清单" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /预览候选数据/ }));
    const preview = await screen.findByRole("dialog", { name: "待入库候选数据预览" });
    expect(within(preview).getByText("IN-1")).toBeInTheDocument();
    expect(within(preview).queryByText("共享站点数据不能自动匹配")).not.toBeInTheDocument();
    fireEvent.click(within(preview).getByRole("button", { name: "Close" }));

    fireEvent.click(screen.getByRole("button", { name: "查看异常数据" }));
    const issues = await screen.findByRole("dialog", { name: "待入库同步异常数据" });
    expect(within(issues).getByText("共享站点数据不能自动匹配")).toBeInTheDocument();
    expect(within(issues).getByRole("columnheader", { name: "入库仓" })).toBeInTheDocument();
    expect(within(issues).getByRole("columnheader", { name: "剩余应收货" })).toBeInTheDocument();
    expect(within(issues).getByRole("columnheader", { name: "关联采购单" })).toBeInTheDocument();
    expect(within(issues).getByText("自营仓")).toBeInTheDocument();
    expect(within(issues).getByText("12")).toBeInTheDocument();
    expect(within(issues).getByRole("button", { name: /下载完整清单/ })).toBeInTheDocument();
    expect(within(issues).queryByText("关联采购单为空")).not.toBeInTheDocument();
    fireEvent.click(within(issues).getByRole("button", { name: "映射错误" }));
    expect(within(issues).getByText("关联采购单为空")).toBeInTheDocument();
    expect(within(issues).queryByText("共享站点数据不能自动匹配")).not.toBeInTheDocument();
    expect(within(issues).queryByText("IN-1")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("当前配置")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /同步待入库数据/ })).toBeInTheDocument();
    expect(screen.getAllByText(/自营仓超收 5 件/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: "自营仓入库批次列表" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "积加采购数据同步" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "统一批次流程" })).not.toBeInTheDocument();
    expect(screen.queryByText("2026-07-21 交货批次")).not.toBeInTheDocument();
  });

  it("shows an indeterminate progress bar while inbound data is syncing", async () => {
    const job = state.inboundSyncStatus.job as Record<string, unknown>;
    state.inboundSyncStatus = {
      ...state.inboundSyncStatus,
      job: { ...job, status: "running", finished_at: null }
    };

    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: AntApp });

    const progress = await screen.findByRole("progressbar", { name: "正在同步待入库数据" });
    expect(progress).toHaveClass("is-indeterminate");
    expect(progress).not.toHaveAttribute("aria-valuenow");
  });

  it("polls only inbound sync status without overlap and fully refreshes once on completion", async () => {
    vi.useFakeTimers();
    const initialFetch = vi.mocked(fetch);
    const requests: string[] = [];
    let statusRequestCount = 0;
    let releaseRunningPoll!: () => void;
    const runningJob = {
      ...(state.inboundSyncStatus.job as Record<string, unknown>),
      status: "running",
      candidate_version_id: null,
      finished_at: null
    };
    const completedStatus = {
      ...state.inboundSyncStatus,
      job: {
        ...(state.inboundSyncStatus.job as Record<string, unknown>),
        status: "succeeded"
      }
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const url = String(input);
        requests.push(url.replace(/^.*(?=\/api\/)/, ""));
        if (url.endsWith("/api/self-operated-inbound-sync") && !init.method) {
          statusRequestCount += 1;
          if (statusRequestCount === 1) {
            return jsonResponse({ ...state.inboundSyncStatus, job: runningJob });
          }
          if (statusRequestCount === 2) {
            return new Promise<Response>((resolve) => {
              releaseRunningPoll = () =>
                resolve(
                  jsonResponse({
                    ...state.inboundSyncStatus,
                    job: runningJob
                  })
                );
            });
          }
          return jsonResponse(completedStatus);
        }
        return initialFetch(input, init);
      })
    );

    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: AntApp });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    requests.length = 0;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(requests).toEqual(["/api/self-operated-inbound-sync"]);

    await act(async () => {
      releaseRunningPoll();
      await vi.advanceTimersByTimeAsync(0);
    });
    requests.length = 0;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(requests).toEqual(
      expect.arrayContaining([
        "/api/self-operated-inbound-sync",
        "/api/batches?workflow=self_operated_inbound&offset=0&limit=12",
        "/api/input-versions",
        "/api/self-operated-overreceipt-rule-versions"
      ])
    );
    expect(requests).toHaveLength(4);
  });
  it("stops inbound polling when leaving the workspace", async () => {
    vi.useFakeTimers();
    state.inboundSyncStatus = {
      ...state.inboundSyncStatus,
      job: { ...(state.inboundSyncStatus.job as Record<string, unknown>), status: "running" }
    };
    const { rerender } = render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: AntApp });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    vi.mocked(fetch).mockClear();
    rerender(<BatchesPage workflow="self_operated_inbound" active={false} onOpen={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
