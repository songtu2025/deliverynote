import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { createDetailBatch, fixtureJob } from "./detailFixtures";
import BatchExportActions from "./BatchExportActions";
import type { useBatchTasks } from "./useBatchTasks";

function show(workflow: "delivery" | "self_operated_inbound", status?: string, unfinishedCount = 0) {
  const startExport = vi.fn(async () => undefined);
  const batch = {
    ...createDetailBatch(),
    workflow,
    jobs: status ? { export: fixtureJob({ kind: "export", status }) } : {}
  };
  renderDetail(
    <BatchExportActions
      batch={batch}
      action={null}
      tasks={{ startExport, downloadResult: vi.fn() } as unknown as ReturnType<typeof useBatchTasks>}
      focusReview={vi.fn()}
      reviewStats={{
        unfinishedCount,
        unfinishedQuantity: unfinishedCount,
        totalCount: unfinishedCount,
        resolvedCount: 0
      }}
    />
  );
  return startExport;
}

describe("自营仓自动生成与重试入口", () => {
  it.each([undefined, "queued", "running"])("自营仓 %s 不要求手动生成", (status) => {
    show("self_operated_inbound", status);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it.each(["failed", "stale"])("无待处理时 %s 可重试生成", (status) => {
    const start = show("self_operated_inbound", status);
    fireEvent.click(screen.getByRole("button", { name: /生成结果/ }));
    expect(start).toHaveBeenCalledOnce();
  });
  it.each(["failed", "stale"])("仍有待处理时 %s 不显示生成或开始审校", (status) => {
    show("self_operated_inbound", status, 1);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("交货批次保留开始审校和生成结果", () => {
    show("delivery", undefined, 1);
    expect(screen.getByRole("button", { name: "开始审校" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /生成结果/ })).toBeInTheDocument();
  });
});
