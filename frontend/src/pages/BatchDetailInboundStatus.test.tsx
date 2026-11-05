import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import BatchSummary from "./batch-detail/BatchSummary";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { fixtureJob } from "./batch-detail/detailFixtures";
import { deferred, jsonResponse } from "./admin/positionDraftTestSupport";

vi.mock("./batch-detail/BatchSummary", () => ({ default: vi.fn(() => <div />) }));

describe("自营仓进度和重试", () => {
  const { state } = setupBatchDetailTest();
  beforeEach(() => {
    state.batch.workflow = "self_operated_inbound";
    state.batch.status = "running";
    state.batch.receipt = { requested_total: 160, issue_count: 0 };
    state.batch.inbound_file = { uploaded: true, original_name: "合成输入.xlsx" };
  });
  afterEach(() => vi.useRealTimers());

  it("已用时间每秒刷新，只重绘状态区，不重绘数量区或追加请求", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-05T00:00:10Z"));
    state.batch.jobs = { compute: fixtureJob({ claimed_at: "2026-11-05T00:00:05" }) };
    const originalFetch = fetch;
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        String(input).endsWith("/api/jobs/88") ? pending.promise : originalFetch(input)
      )
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("status")).toHaveTextContent("正在计算（2/3，已用 5 秒）");
    const summaryRenders = vi.mocked(BatchSummary).mock.calls.length;
    const requests = vi.mocked(fetch).mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("status")).toHaveTextContent("正在计算（2/3，已用 7 秒）");
    expect(vi.mocked(BatchSummary).mock.calls).toHaveLength(summaryRenders);
    expect(fetch).toHaveBeenCalledTimes(requests);
  });

  it.each(["prepare", "compute", "export"] as const)("%s 失败展示原因并复用原入口重试", async (kind) => {
    state.batch.status = kind === "export" ? "succeeded" : "failed";
    state.batch.jobs = { [kind]: fixtureJob({ kind, status: "failed", error_message: "合成失败原因" }) };
    const originalFetch = fetch;
    const endpoint = kind === "prepare" ? "preflight" : kind;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("purchase-snapshot"))
          return Promise.resolve(
            jsonResponse({
              state: "ready",
              job: fixtureJob({ kind: "purchase_snapshot", status: "succeeded" }),
              items: [],
              total: 0
            })
          );
        if (url.endsWith("/api/jobs/88")) return deferred<Response>().promise;
        if (url.endsWith("/" + endpoint) && init?.method === "POST") {
          state.batch.jobs = { [kind]: fixtureJob({ kind, status: "queued" }) };
          state.batch.status = "queued";
          return Promise.resolve(jsonResponse(kind === "prepare" ? state.batch : state.batch.jobs[kind]));
        }
        return originalFetch(input, init);
      })
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent("合成失败原因");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("排队中"));
    const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe("/api/batches/7/" + endpoint);
  });
});
