import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { fixtureJob } from "./batch-detail/detailFixtures";
import { deferred, jsonResponse } from "./admin/positionDraftTestSupport";

function interceptTaskRequests(responseFor: (url: string) => Response | Promise<Response> | undefined) {
  const originalFetch = fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => responseFor(String(input)) ?? originalFetch(input, init))
  );
}

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
    ["draft", "2 个文件已上传，确认顺序后预检并计算"],
    ["preflight_ready", "预检通过，可以计算"],
    ["failed", "计算失败"]
  ])("准确显示 %s 并保持静止", async (status, title) => {
    state.batch.status = status;
    state.batch.error_message = status === "failed" ? "合成失败原因" : null;
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText(state.batch.name);
    const task = within(screen.getByRole("region", { name: "当前批次任务" }));
    expect(task.getByRole("status")).toHaveTextContent(title);
    if (status === "failed") {
      expect(task.getByRole("status")).toHaveTextContent("合成失败原因");
      expect(task.getByRole("button", { name: /预检并计算/ })).toBeEnabled();
      expect(task.queryByRole("button", { name: /重新计算/ })).not.toBeInTheDocument();
    }
    expect(container.querySelector(".batch-task-spinner")).not.toBeInTheDocument();
  });

  it("预检通过后才启动计算，按顺序发送请求并刷新批次", async () => {
    state.batch.status = "draft";
    const pending = deferred<Response>();
    interceptTaskRequests((url) => {
      if (url.endsWith("/preflight")) return pending.promise;
      if (url.endsWith("/compute")) {
        state.batch.status = "queued";
        return jsonResponse(fixtureJob({ status: "queued" }));
      }
    });
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const button = await screen.findByRole("button", { name: /预检并计算/ });
    fireEvent.click(button);
    expect(button).toHaveClass("ant-btn-primary", "ant-btn-loading");
    expect(
      vi
        .mocked(fetch)
        .mock.calls.filter(([, init]) => init?.method === "POST")
        .map(([url, init]) => [url, init?.method, init?.body])
    ).toEqual([["/api/batches/7/preflight", "POST", undefined]]);
    state.batch.status = "preflight_ready";
    pending.resolve(jsonResponse(state.batch));
    expect(await screen.findByText("预检通过，已开始计算")).toBeInTheDocument();
    const requests = vi.mocked(fetch).mock.calls;
    expect(
      requests.filter(([, init]) => init?.method === "POST").map(([url, init]) => [url, init?.method, init?.body])
    ).toEqual([
      ["/api/batches/7/preflight", "POST", undefined],
      ["/api/batches/7/compute", "POST", undefined]
    ]);
    const computeIndex = requests.findIndex(([url]) => String(url).endsWith("/compute"));
    expect(requests.slice(computeIndex + 1).some(([url]) => url === "/api/batches/7")).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("计算排队中");
  });

  it.each([false, true])("启动计算失败后刷新批次，保留原错误（刷新抛错：%s）", async (refreshFails) => {
    state.batch.status = "draft";
    let computeFailed = false;
    interceptTaskRequests((url) => {
      if (url.endsWith("/preflight")) {
        state.batch.status = "preflight_ready";
        return jsonResponse(state.batch);
      }
      if (url.endsWith("/compute")) {
        computeFailed = true;
        return new Response(JSON.stringify({ detail: "计算启动失败" }), { status: 500 });
      }
      if (refreshFails && computeFailed && url.endsWith("/api/batches/7")) {
        return new Response(JSON.stringify({ detail: "未登录" }), { status: 401 });
      }
    });
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /预检并计算/ }));
    expect(await screen.findByText("计算启动失败")).toBeInTheDocument();
    const requests = vi.mocked(fetch).mock.calls;
    const computeIndex = requests.findIndex(([url]) => String(url).endsWith("/compute"));
    expect(requests.slice(computeIndex + 1).some(([url]) => url === "/api/batches/7")).toBe(true);
    expect(screen.queryByText("预检通过，已开始计算")).not.toBeInTheDocument();
    if (!refreshFails) {
      const task = within(screen.getByRole("region", { name: "当前批次任务" }));
      expect(task.getByRole("status")).toHaveTextContent("预检通过，可以计算");
      expect(task.getByRole("button", { name: /开始计算/ })).toBeEnabled();
      expect(task.queryByRole("button", { name: /预检并计算/ })).not.toBeInTheDocument();
    }
  });

  it("预检返回未就绪状态时只刷新，不启动计算或提示成功", async () => {
    state.batch.status = "draft";
    interceptTaskRequests((url) => {
      if (url.endsWith("/preflight")) {
        state.batch.status = "failed";
        return jsonResponse(state.batch);
      }
    });
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /预检并计算/ }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("计算失败"));
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("/compute"))).toBe(false);
    expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
  });

  it("单文件有待处理记录时仍使用单文件下载入口", async () => {
    state.batch.files = [{ ...state.batch.files[0], download_ready: true }];
    state.batch.file_count = 1;
    state.batch.download_ready = true;
    state.exceptions = [state.exceptions[0]];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "批次任务状态" }));
    await waitFor(() => expect(task.getByRole("status")).toHaveTextContent("1 条待审校，共 60 件"));
    expect(task.getByRole("button", { name: "开始审校" })).toBeEnabled();
    expect(task.queryByRole("button", { name: /下载结果/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 1" }));
    expect(screen.getByRole("button", { name: "下载单文件结果" })).toBeEnabled();
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
    expect(task.getByRole("status")).not.toHaveTextContent(/0 条待审校/);
    pending.resolve(new Response(JSON.stringify({ detail: "统计读取失败" }), { status: 500 }));
    expect(await screen.findByText("统计读取失败")).toBeInTheDocument();
    expect(task.getByText("审校统计暂不可用，请重试读取批次。")).toBeInTheDocument();
    expect(task.getByRole("status")).not.toHaveTextContent(/0 条待审校/);
  });

  it("筛选审校记录不改变顶部的全批次统计", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "批次任务状态" }));
    await waitFor(() => expect(task.getByRole("status")).toHaveTextContent("4 条待审校，共 107 件"));
    const bar = screen.getByRole("img", { name: "可导入 100，待处理 60" });
    expect(bar.children).toHaveLength(2);
    expect(bar.children[1]).toHaveStyle({ flexGrow: "60" });
    expect(screen.queryByText(/保留待处理/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索待处理记录" }), { target: { value: "SKU-B" } });
    await waitFor(() => expect(screen.queryByText("SKU-A")).not.toBeInTheDocument());
    expect(task.getByRole("status")).toHaveTextContent("4 条待审校，共 107 件");
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
