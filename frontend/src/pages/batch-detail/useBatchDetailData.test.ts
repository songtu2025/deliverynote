import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";
import { setupBatchDetailTest } from "../batchDetailTestSupport";
import { useBatchDetailData } from "./useBatchDetailData";

describe("批次详情请求生命周期", () => {
  const { state, exceptionPage } = setupBatchDetailTest();

  it("切换批次后忽略旧批次晚回的概览、审校和筛选结果", async () => {
    const oldBatch = deferred<Response>();
    const oldExceptions = deferred<Response>();
    const oldFilters = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/batches/7")) return oldBatch.promise;
        if (url.includes("/batches/7/exceptions?")) return oldExceptions.promise;
        if (url.endsWith("/batches/7/exceptions/filters")) return oldFilters.promise;
        if (url.endsWith("/batches/8")) return Promise.resolve(jsonResponse({ ...state.batch, id: 8, name: "新批次" }));
        if (url.includes("/batches/8/exceptions?"))
          return Promise.resolve(jsonResponse({ ...exceptionPage(url), items: [] }));
        return Promise.resolve(jsonResponse({ reasons: ["新原因"], sites: [], scales: [], stocking: [] }));
      })
    );
    const setTarget = vi.fn();
    const { result, rerender } = renderHook(({ batchId }) => useBatchDetailData(batchId, false, setTarget), {
      initialProps: { batchId: 7 }
    });
    rerender({ batchId: 8 });
    await waitFor(() => expect(result.current.batch?.id).toBe(8));
    await act(async () => {
      oldBatch.resolve(jsonResponse(state.batch));
      oldExceptions.resolve(jsonResponse(exceptionPage("/batches/7/exceptions?")));
      oldFilters.resolve(jsonResponse({ reasons: ["旧原因"], sites: [], scales: [], stocking: [] }));
    });
    expect(result.current.batch?.name).toBe("新批次");
    expect(result.current.review.exceptions).toEqual([]);
    expect(result.current.review.exceptionFilters.reasons).toEqual(["新原因"]);
    expect(setTarget).not.toHaveBeenCalled();
  });

  it("并发刷新仅应用最后一次请求，旧请求不提前结束加载状态", async () => {
    const originalFetch = fetch;
    const first = deferred<Response>();
    const second = deferred<Response>();
    let batchRequests = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/batches/7")) return ++batchRequests === 1 ? first.promise : second.promise;
        return originalFetch(input, init);
      })
    );
    const setTarget = vi.fn();
    const { result } = renderHook(() => useBatchDetailData(7, false, setTarget));
    let refresh: Promise<unknown>;
    act(() => {
      refresh = result.current.load();
    });
    await act(async () => {
      first.resolve(jsonResponse({ ...state.batch, name: "旧请求" }));
    });
    expect(result.current.batch).toBeNull();
    expect(result.current.loading).toBe(true);
    await act(async () => {
      second.resolve(jsonResponse({ ...state.batch, name: "最新请求" }));
      await refresh;
    });
    expect(result.current.batch?.name).toBe("最新请求");
    expect(result.current.loading).toBe(false);
    expect(result.current.review.exceptionsLoading).toBe(false);
  });

  it("退出页面后不应用延迟审校结果或打开待导航的记录", async () => {
    const originalFetch = fetch;
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).includes("/exceptions?") ? pending.promise : originalFetch(input, init)
      )
    );
    const setTarget = vi.fn();
    const { result, unmount } = renderHook(() => useBatchDetailData(7, false, setTarget));
    await waitFor(() => expect(result.current.batch?.id).toBe(7));
    result.current.review.queueReviewDirection("first");
    unmount();
    await act(async () => {
      pending.resolve(jsonResponse(exceptionPage("/batches/7/exceptions?")));
    });
    expect(setTarget).not.toHaveBeenCalled();
  });
});
