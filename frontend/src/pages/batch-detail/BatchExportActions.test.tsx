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

describe("下载处理中反馈", () => {
  it("正在下载的按钮显示处理中，其他下载按钮暂不可点", () => {
    const original = createDetailBatch();
    const batch = {
      ...original,
      download_ready: true,
      merged_download_ready: true,
      files: original.files.slice(0, 2).map((file) => ({ ...file, download_ready: true }))
    };
    renderDetail(
      <BatchExportActions
        batch={batch}
        action={`download:/api/batches/${batch.id}/download-merged`}
        tasks={{ downloadResult: vi.fn(), startExport: vi.fn() } as unknown as ReturnType<typeof useBatchTasks>}
        focusReview={vi.fn()}
        reviewStats={{ unfinishedCount: 0, unfinishedQuantity: 0, totalCount: 0, resolvedCount: 0 }}
      />
    );
    expect(screen.getByRole("button", { name: /下载合并结果/ })).toHaveClass("ant-btn-loading");
    expect(screen.getByRole("button", { name: /下载分文件 ZIP/ })).toBeDisabled();
  });
});

describe("自营仓自动生成与重试入口", () => {
  it.each([false, true])("有待处理时下载仍是主按钮，多文件：%s", (multiple) => {
    const original = createDetailBatch();
    const batch = {
      ...original,
      workflow: "self_operated_inbound" as const,
      download_ready: true,
      merged_download_ready: multiple,
      files: original.files.slice(0, multiple ? 2 : 1).map((file) => ({ ...file, download_ready: true }))
    };
    const download = vi.fn();
    renderDetail(
      <BatchExportActions
        batch={batch}
        action={null}
        tasks={{ downloadResult: download, startExport: vi.fn() } as unknown as ReturnType<typeof useBatchTasks>}
        focusReview={vi.fn()}
        reviewStats={{ unfinishedCount: 2, unfinishedQuantity: 8, totalCount: 2, resolvedCount: 0 }}
      />
    );
    const button = screen.getByRole("button", { name: multiple ? /下载合并结果/ : /下载结果/ });
    expect(button).toHaveClass("ant-btn-primary");
    fireEvent.click(button);
    expect(download).toHaveBeenCalledOnce();
    if (multiple) expect(screen.getByRole("button", { name: /下载分文件 ZIP/ })).toBeEnabled();
  });
  it.each(["queued", "running"])("自营仓导出 %s 时不要求手动生成", (status) => {
    show("self_operated_inbound", status);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("自营仓没有导出任务（旧批次）时可手动生成", () => {
    const start = show("self_operated_inbound", undefined, 1);
    fireEvent.click(screen.getByRole("button", { name: /生成结果/ }));
    expect(start).toHaveBeenCalledOnce();
  });
  it.each(["failed", "stale"])("无待处理时 %s 可重试生成", (status) => {
    const start = show("self_operated_inbound", status);
    fireEvent.click(screen.getByRole("button", { name: /生成结果/ }));
    expect(start).toHaveBeenCalledOnce();
  });
  it.each(["failed", "stale"])("仍有待处理时 %s 可重试生成", (status) => {
    const start = show("self_operated_inbound", status, 1);
    fireEvent.click(screen.getByRole("button", { name: /生成结果/ }));
    expect(start).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "开始审校" })).not.toBeInTheDocument();
  });
  it("交货批次保留开始审校和生成结果", () => {
    show("delivery", undefined, 1);
    expect(screen.getByRole("button", { name: "开始审校" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /生成结果/ })).toBeInTheDocument();
  });
});
