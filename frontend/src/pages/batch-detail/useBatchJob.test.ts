import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Batch, Job } from "../../types";
import { getBatchJob } from "../../batchDetailApi";
import { deferred } from "../admin/positionDraftTestSupport";
import { createDetailBatch, fixtureJob } from "./detailFixtures";
import { useBatchJob } from "./useBatchJob";

const feedback = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("antd", () => ({ App: { useApp: () => ({ message: feedback }) } }));
vi.mock("../../batchDetailApi", () => ({ getBatchJob: vi.fn() }));

const runningBatch = (): Batch => ({ ...createDetailBatch(), jobs: { compute: fixtureJob() } });

describe("批次任务轮询生命周期", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("退出页面后忽略仍在途中的任务响应", async () => {
    const response = deferred<Job>();
    vi.mocked(getBatchJob).mockReturnValue(response.promise);
    const load = vi.fn(async () => null);
    const { unmount } = renderHook(() => useBatchJob(runningBatch(), load));
    unmount();
    await act(async () => {
      response.resolve(fixtureJob({ status: "succeeded" }));
    });
    expect(load).not.toHaveBeenCalled();
    expect(feedback.success).not.toHaveBeenCalled();
    expect(feedback.error).not.toHaveBeenCalled();
  });

  it("完成后的刷新晚于页面退出时不再发成功提示", async () => {
    vi.mocked(getBatchJob).mockResolvedValue(fixtureJob({ status: "succeeded" }));
    const refreshing = deferred<null>();
    const load = vi.fn(() => refreshing.promise);
    const { unmount } = renderHook(() => useBatchJob(runningBatch(), load));
    await waitFor(() => expect(load).toHaveBeenCalledWith(true));
    unmount();
    await act(async () => {
      refreshing.resolve(null);
    });
    expect(feedback.success).not.toHaveBeenCalled();
  });

  it("使用最新刷新回调，状态刷新后仍只提示一次完成", async () => {
    const response = deferred<Job>();
    const refreshing = deferred<null>();
    vi.mocked(getBatchJob).mockReturnValue(response.promise);
    const originalLoad = vi.fn(() => refreshing.promise);
    const latestLoad = vi.fn(() => refreshing.promise);
    const batch = runningBatch();
    const { rerender } = renderHook(({ current, load }) => useBatchJob(current, load), {
      initialProps: { current: batch, load: originalLoad }
    });
    rerender({ current: batch, load: latestLoad });
    await act(async () => {
      response.resolve(fixtureJob({ status: "succeeded" }));
    });
    expect(originalLoad).not.toHaveBeenCalled();
    expect(latestLoad).toHaveBeenCalledOnce();
    rerender({ current: { ...batch, jobs: { compute: fixtureJob({ status: "succeeded" }) } }, load: latestLoad });
    await act(async () => {
      refreshing.resolve(null);
    });
    expect(feedback.success).toHaveBeenCalledExactlyOnceWith("批次计算完成");
    expect(getBatchJob).toHaveBeenCalledOnce();
  });

  it("切换批次后不把旧批次的完成提示发到新页面", async () => {
    vi.mocked(getBatchJob).mockResolvedValue(fixtureJob({ status: "succeeded" }));
    const refreshing = deferred<null>();
    const load = vi.fn(() => refreshing.promise);
    const { rerender } = renderHook(({ batch }) => useBatchJob(batch, load), {
      initialProps: { batch: runningBatch() }
    });
    await waitFor(() => expect(load).toHaveBeenCalledOnce());
    rerender({ batch: { ...createDetailBatch(), id: 8 } });
    await act(async () => {
      refreshing.resolve(null);
    });
    expect(feedback.success).not.toHaveBeenCalled();
    expect(feedback.error).not.toHaveBeenCalled();
  });

  it("等待下一轮期间退出页面会停止后续请求", async () => {
    vi.useFakeTimers();
    vi.mocked(getBatchJob).mockResolvedValue(fixtureJob());
    const load = vi.fn(async () => null);
    const { unmount } = renderHook(() => useBatchJob(runningBatch(), load));
    await act(async () => {
      await Promise.resolve();
    });
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(getBatchJob).toHaveBeenCalledOnce();
    expect(load).not.toHaveBeenCalled();
  });
});
