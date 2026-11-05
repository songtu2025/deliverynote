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
  it("自营仓只在结果可下载时提示一次，同一 Job 再次执行可再次提示", async () => {
    const pending = deferred<Job>();
    vi.mocked(getBatchJob).mockReturnValue(pending.promise);
    const load = vi.fn(async () => null);
    const current: Batch = { ...runningBatch(), workflow: "self_operated_inbound" };
    const { rerender } = renderHook(({ batch }) => useBatchJob(batch, load), { initialProps: { batch: current } });
    await act(async () => {
      pending.resolve(fixtureJob({ status: "succeeded" }));
    });
    expect(feedback.success).not.toHaveBeenCalled();
    const exported = fixtureJob({ id: 89, kind: "export", status: "running" });
    vi.mocked(getBatchJob).mockReturnValue(deferred<Job>().promise);
    rerender({ batch: { ...current, jobs: { export: exported } } });
    const ready: Batch = {
      ...current,
      download_ready: true,
      jobs: { export: { ...exported, status: "succeeded", finished_at: "2026-11-05T00:00:10Z" } }
    };
    rerender({ batch: ready });
    rerender({ batch: { ...ready } });
    expect(feedback.success).toHaveBeenCalledExactlyOnceWith("计算完成，结果已生成");
    rerender({ batch: { ...current, jobs: { export: exported } } });
    rerender({
      batch: { ...ready, jobs: { export: { ...ready.jobs!.export!, finished_at: "2026-11-05T00:00:20Z" } } }
    });
    expect(feedback.success).toHaveBeenCalledTimes(2);
  });

  it("重进已完成的自营仓批次不重复播报历史结果", () => {
    const batch: Batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound",
      download_ready: true,
      jobs: { export: fixtureJob({ kind: "export", status: "succeeded" }) }
    };
    renderHook(() => useBatchJob(batch, vi.fn()));
    expect(feedback.success).not.toHaveBeenCalled();
  });

  it("切走后返回已完成的自营仓批次不播报离开期间的完成", () => {
    vi.mocked(getBatchJob).mockReturnValue(deferred<Job>().promise);
    const current: Batch = { ...runningBatch(), workflow: "self_operated_inbound" };
    const { rerender } = renderHook(({ batch }) => useBatchJob(batch, vi.fn()), {
      initialProps: { batch: current }
    });
    rerender({ batch: { ...createDetailBatch(), id: 8 } });
    rerender({
      batch: {
        ...current,
        download_ready: true,
        jobs: {
          export: fixtureJob({ kind: "export", status: "succeeded" })
        }
      }
    });
    expect(feedback.success).not.toHaveBeenCalled();
  });

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

  it("任务从排队变为执行中时立即更新显示状态，不等批次刷新", async () => {
    vi.mocked(getBatchJob).mockResolvedValue(fixtureJob({ status: "running" }));
    const load = vi.fn(async () => null);
    const queued: Batch = { ...createDetailBatch(), jobs: { compute: fixtureJob({ status: "queued" }) } };
    const { result } = renderHook(() => useBatchJob(queued, load));
    expect(result.current?.status).toBe("queued");
    await waitFor(() => expect(result.current?.status).toBe("running"));
    expect(load).not.toHaveBeenCalled();
  });
});
