import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import InboundBulkActions from "./InboundBulkActions";

const first = { ...createDetailExceptions()[3], manual_quantity: 8, transferred_quantity: 2, offline_quantity: 1 };
const second = { ...first, id: first.id + 100, manual_quantity: 4, transferred_quantity: 0, offline_quantity: 0 };
const batch = {
  ...createDetailBatch(),
  workflow: "self_operated_inbound" as const,
  manual_allowance_disabled_reason: null
};
afterEach(() => vi.unstubAllGlobals());

function showSelectedRows() {
  const saved = vi.fn(async () => undefined);
  renderDetail(<InboundBulkActions batch={batch} records={[first, second]} onSaved={saved} />);
  return saved;
}

describe("勾选后的批量处理", () => {
  it("批量线下处理一次提交全部所选行并刷新", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(batch)));
    const saved = showSelectedRows();
    fireEvent.change(screen.getByRole("textbox", { name: "线下备注（选填）" }), { target: { value: "统一备注" } });
    fireEvent.click(screen.getByRole("button", { name: "线下处理" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`/api/batches/${batch.id}/offline-handling`);
    expect(JSON.parse(init?.body as string).items).toEqual([
      { exception_id: first.id, quantity: 6, note: "统一备注" },
      { exception_id: second.id, quantity: 4, note: "统一备注" }
    ]);
    expect(await screen.findByText("已线下处理 2 条，正在更新结果")).toBeVisible();
  });
  it("批量线下处理失败时整体不保存并提示原因", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse({ detail: "记录已变化" }, 409)));
    const saved = showSelectedRows();
    fireEvent.click(screen.getByRole("button", { name: "线下处理" }));
    expect(await screen.findByText("记录已变化")).toBeVisible();
    expect(saved).not.toHaveBeenCalled();
  });
  it("不再提供批量追加；空选禁用线下处理并说明原因", async () => {
    const { rerender } = renderDetail(
      <InboundBulkActions batch={batch} records={[{ ...first, reason: "产品信息未匹配" }]} onSaved={vi.fn()} />
    );
    expect(screen.queryByRole("button", { name: "追加超收" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "线下处理" })).toBeEnabled();
    rerender(<InboundBulkActions batch={batch} records={[]} onSaved={vi.fn()} />);
    const offline = screen.getByRole("button", { name: "线下处理" });
    expect(offline).toBeDisabled();
    fireEvent.focus(offline.parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("请先勾选待处理行");
  });
});
