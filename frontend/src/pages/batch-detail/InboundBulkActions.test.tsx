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
  it("同一供应商、SKU、站点聚合剩余量，一次追加并统一刷新", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(batch))
    );
    const saved = showSelectedRows();
    fireEvent.click(screen.getByRole("button", { name: "追加超收" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledOnce();
    const input = JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string);
    expect(input.items).toHaveLength(1);
    expect(input.items[0]).toMatchObject({ quantity: 9, reason: "" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each([false, true])("线下逐条处理后统一刷新并汇总，首条失败：%s", async (failFirst) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(failFirst ? jsonResponse({ detail: "记录已变化" }, 409) : jsonResponse(first))
        .mockResolvedValueOnce(jsonResponse(second))
    );
    const saved = showSelectedRows();
    fireEvent.click(screen.getByRole("button", { name: "线下处理" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(init?.body as string).quantity)).toEqual([6, 4]);
    const summary = failFirst ? "已线下处理 1 条，失败 1 条：记录已变化" : "已线下处理 2 条";
    expect(await screen.findByText(summary)).toBeVisible();
  });

  it("不适用追加的行禁用并提供 Tooltip，空选禁用所有操作", async () => {
    const { rerender } = renderDetail(
      <InboundBulkActions batch={batch} records={[{ ...first, reason: "产品信息未匹配" }]} onSaved={vi.fn()} />
    );
    const append = screen.getByRole("button", { name: "追加超收" });
    expect(append).toBeDisabled();
    fireEvent.focus(append.parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("所选行的待处理原因不适用追加超收");
    expect(screen.getByRole("button", { name: "线下处理" })).toBeEnabled();
    rerender(<InboundBulkActions batch={batch} records={[]} onSaved={vi.fn()} />);
    expect(screen.getByRole("button", { name: "追加超收" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "线下处理" })).toBeDisabled();
  });
});
