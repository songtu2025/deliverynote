import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { fixtureJob } from "./batch-detail/detailFixtures";
import { deferred, jsonResponse } from "./admin/positionDraftTestSupport";

describe("交货批次任务状态条", () => {
  const { state } = setupBatchDetailTest();

  it.each([
    ["compute", "queued", "计算排队中", true],
    ["compute", "running", "正在计算", true],
    ["export", "queued", "结果排队中", true],
    ["export", "running", "正在生成结果", true]
  ] as const)("刷新后恢复 %s/%s 的真实状态", async (kind, status, title, spinning) => {
    state.batch.jobs = { [kind]: fixtureJob({ kind, status }) };
    const { container, unmount } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent(title);
    expect(Boolean(container.querySelector(".batch-task-spinner"))).toBe(spinning);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    unmount();
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent(title);
  });

  it.each([
    ["draft", "2 个文件已上传，确认顺序后预检"],
    ["preflight_ready", "预检通过，可以计算"],
    ["failed", "计算失败"]
  ])("准确显示 %s 并保持静止", async (status, title) => {
    state.batch.status = status;
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent(title);
    expect(container.querySelector(".batch-task-spinner")).not.toBeInTheDocument();
  });

  it("单文件有待处理记录时仍使用单文件下载入口", async () => {
    state.batch.files = [{ ...state.batch.files[0], download_ready: true }];
    state.batch.file_count = 1;
    state.batch.download_ready = true;
    state.exceptions = [state.exceptions[0]];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "批次任务状态" }));
    expect(await task.findByText("1 条待审校，共 60 件")).toBeInTheDocument();
    expect(task.getByRole("button", { name: /下载结果/ })).toBeEnabled();
    expect(task.queryByRole("button", { name: /下载合并结果|下载分文件 ZIP/ })).not.toBeInTheDocument();
    expect(task.getByText("结果可下载")).toBeInTheDocument();
  });

  it("统计加载前和加载失败时不显示虚假的零条未完成", async () => {
    const pending = deferred<Response>();
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("/exceptions?") ? pending.promise : originalFetch(input, init)
      )
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "批次任务状态" }));
    expect(task.getByText("正在读取审校统计…")).toBeInTheDocument();
    expect(task.queryByText(/0 条待审校/)).not.toBeInTheDocument();
    pending.resolve(new Response(JSON.stringify({ detail: "统计读取失败" }), { status: 500 }));
    expect(await screen.findByText("统计读取失败")).toBeInTheDocument();
    expect(task.getByText("审校统计暂不可用，请重试读取批次。")).toBeInTheDocument();
    expect(task.queryByText(/0 条待审校/)).not.toBeInTheDocument();
  });

  it("筛选审校记录不改变顶部的全批次统计", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "批次任务状态" }));
    expect(await task.findByText("4 条待审校，共 107 件")).toBeInTheDocument();
    const bar = screen.getByRole("img", { name: "可导入 100，待处理 60" });
    expect(bar.children).toHaveLength(2);
    expect(bar.children[1]).toHaveStyle({ flexGrow: "60" });
    expect(screen.queryByText(/保留待处理/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索待处理记录" }), { target: { value: "SKU-B" } });
    await waitFor(() => expect(screen.queryByText("SKU-A")).not.toBeInTheDocument());
    expect(task.getByText("4 条待审校，共 107 件")).toBeInTheDocument();
  });

  it("计算任务完成后更新审校状态并停止加载标记", async () => {
    state.batch.jobs = { compute: fixtureJob() };
    const pending = deferred<Response>();
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("/api/jobs/88") ? pending.promise : originalFetch(input, init)
      )
    );
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent("正在计算");
    state.batch.jobs = { compute: fixtureJob({ status: "succeeded" }) };
    pending.resolve(jsonResponse(state.batch.jobs.compute));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("4 条待审校，共 107 件"));
    expect(container.querySelector(".batch-task-spinner")).not.toBeInTheDocument();
  });

  it("导出失败时保留重新生成入口并停止加载标记", async () => {
    state.batch.jobs = { export: fixtureJob({ kind: "export", status: "failed", error_message: "生成失败" }) };
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent("结果生成失败");
    expect(screen.getByRole("button", { name: /生成结果/ })).toBeEnabled();
    expect(container.querySelector(".batch-task-spinner")).not.toBeInTheDocument();
  });
});
