import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Batch } from "../../types";
import type { InboundAllocations } from "../../inboundExceptionApi";
import { deferred } from "../admin/positionDraftTestSupport";
import { createDetailBatch, fixtureJob } from "./detailFixtures";
import { useInboundRecalculation } from "./useInboundRecalculation";

const original: Batch = {
  ...createDetailBatch(),
  workflow: "self_operated_inbound",
  download_ready: true,
  jobs: {
    compute: fixtureJob({ status: "succeeded", finished_at: "2026-11-05T00:00:01Z" }),
    export: fixtureJob({ id: 89, kind: "export", status: "succeeded", finished_at: "2026-11-05T00:00:02Z" })
  }
};
const allocations: InboundAllocations = {
  batch_updated_at: "2026-11-05T00:00:00Z",
  history_captured_at: null,
  items: [{ id: "1", current_quantity: 10 } as InboundAllocations["items"][number]]
};
function recalculated(computeStatus = "succeeded", exportStatus = "succeeded"): Batch {
  return {
    ...original,
    download_ready: exportStatus === "succeeded",
    jobs: {
      compute: fixtureJob({ status: computeStatus, claimed_at: "2026-11-05T00:00:10Z", error_message: "重算失败" }),
      export: fixtureJob({
        id: 89,
        kind: "export",
        status: exportStatus,
        claimed_at: "2026-11-05T00:00:20Z",
        error_message: "生成失败"
      })
    }
  };
}

describe("抽屉重算跟随已有任务链", () => {
  it("计算和导出完成前持续锁定，完成后只刷新一次并按新汇总提示差值", async () => {
    const response = deferred<InboundAllocations | null>();
    const reload = vi.fn(() => response.promise);
    const saved = vi.fn(async () => undefined);
    const { result, rerender } = renderHook(
      ({ batch }) =>
        useInboundRecalculation({
          batch,
          data: allocations,
          reload,
          onSaved: saved
        }),
      { initialProps: { batch: original } }
    );
    await act(async () => {
      await result.current.saved();
    });
    expect(result.current.busy).toBe(true);
    expect(saved).toHaveBeenCalledOnce();
    rerender({ batch: recalculated("running", "stale") });
    rerender({ batch: recalculated("succeeded", "queued") });
    expect(result.current.busy).toBe(true);
    expect(reload).not.toHaveBeenCalled();
    rerender({ batch: recalculated() });
    rerender({ batch: recalculated() });
    expect(reload).toHaveBeenCalledOnce();
    expect(result.current.busy).toBe(true);
    await act(async () => {
      response.resolve({
        ...allocations,
        items: [{ ...allocations.items[0], current_quantity: 20 }],
        remaining_quantity: 5
      });
    });
    expect(result.current.busy).toBe(false);
    expect(result.current.feedback).toEqual({ error: false, text: "本次分配 +10，待处理剩余 5" });
  });

  it.each([
    ["failed", "stale", "重算失败"],
    ["succeeded", "failed", "生成失败"]
  ])("%s/%s 失败展示原因并解锁，不用旧数据伪造变化", async (compute, exported, reason) => {
    const reload = vi.fn();
    const { result, rerender } = renderHook(
      ({ batch }) => useInboundRecalculation({ batch, data: allocations, reload }),
      { initialProps: { batch: original } }
    );
    await act(async () => {
      await result.current.saved();
    });
    rerender({ batch: recalculated(compute, exported) });
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.feedback).toEqual({ error: true, text: reason });
    expect(reload).not.toHaveBeenCalled();
  });

  it("分配刷新失败会解锁并保留明确错误", async () => {
    const { result, rerender } = renderHook(
      ({ batch }) =>
        useInboundRecalculation({
          batch,
          data: allocations,
          reload: vi.fn(async () => null)
        }),
      { initialProps: { batch: original } }
    );
    await act(async () => {
      await result.current.saved();
    });
    rerender({ batch: recalculated() });
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.feedback?.error).toBe(true);
  });
});
