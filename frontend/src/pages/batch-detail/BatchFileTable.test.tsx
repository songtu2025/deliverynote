import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { createDetailBatch } from "./detailFixtures";
import BatchFileTable from "./BatchFileTable";
import type { BatchFiles } from "./useBatchFiles";

function show(action: string | null) {
  const batch = createDetailBatch();
  const files = batch.files.slice(0, 2).map((file) => ({ ...file, download_ready: true }));
  const actions = { move: vi.fn(), removeFile: vi.fn() } as unknown as BatchFiles;
  renderDetail(
    <BatchFileTable
      batch={batch}
      files={files}
      loading={false}
      computed
      canEditFiles
      actions={actions}
      action={action}
      downloadResult={vi.fn()}
      startExport={vi.fn()}
    />
  );
  return files;
}

describe("来源文件行处理中反馈", () => {
  it("没有进行中的操作时文件行按钮可用", () => {
    const [first] = show(null);
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByRole("button", { name: `下移 ${first.original_name}` })).toBeEnabled();
  });
  it("下移进行中锁定所有文件行操作", () => {
    const [first, second] = show(`order:${createDetailBatch().files[0].id}:1`);
    expect(screen.getByRole("button", { name: `下移 ${first.original_name}` })).toHaveClass("ant-btn-loading");
    expect(screen.getByRole("button", { name: `上移 ${second.original_name}` })).toBeDisabled();
    expect(screen.getByRole("button", { name: `删除 ${second.original_name}` })).toBeDisabled();
    expect(screen.getAllByRole("button", { name: "下载单文件结果" })[0]).toBeDisabled();
  });
  it("删除进行中在对应删除按钮显示处理中", () => {
    const [, second] = show(`delete:${createDetailBatch().files[1].id}`);
    expect(screen.getByRole("button", { name: `删除 ${second.original_name}` })).toHaveClass("ant-btn-loading");
  });
});
