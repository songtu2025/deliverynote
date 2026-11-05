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
  it.each([false, true])("线下逐条处理后统一刷新并汇总，首条失败：%s", async (failFirst) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(failFirst ? jsonResponse({ detail: "记录已变化" }, 409) : jsonResponse(first))
        .mockResolvedValueOnce(jsonResponse(second))
    );
    const saved = showSelectedRows();
    fireEvent.change(screen.getByRole("textbox", { name: "线下备注（选填）" }), { target: { value: "统一备注" } });
    fireEvent.click(screen.getByRole("button", { name: "线下处理" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(init?.body as string).quantity)).toEqual([6, 4]);
    expect(vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(init?.body as string).note)).toEqual([
      "统一备注",
      "统一备注"
    ]);
    const summary = failFirst ? "已线下处理 1 条，失败 1 条：记录已变化" : "已线下处理 2 条";
    expect(await screen.findByText(summary)).toBeVisible();
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
