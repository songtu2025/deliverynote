import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailExceptions } from "./detailFixtures";
import SelfOperatedExceptionDetails from "./SelfOperatedExceptionDetails";

describe("自营仓异常依据", () => {
  const exception = {
    ...createDetailExceptions()[0],
    delivery_quantity: 80,
    allocated_quantity: 72,
    purchase_allocated_quantity: 67,
    overreceipt_allocated_quantity: 5,
    manual_quantity: 8
  };
  const allocation = {
    batch_updated_at: "2026-10-30T00:00:00",
    history_captured_at: "2026-10-29T00:00:00Z",
    items: [
      {
        id: "1",
        po_code: "PO-原分配",
        delivery_no: "LN-1",
        inbound_no: "WV-1",
        site: "AMAZON:SEEKWAY:US",
        warehouse: "仓库甲",
        history_quantity: 3,
        normal_quantity: 67,
        overreceipt_quantity: 5,
        current_quantity: 72
      }
    ]
  };
  const purchases = {
    queried_at: "2026-10-30T01:00:00Z",
    items: [
      { id: "1", po_code: "PO-US", site: "AMAZON:SEEKWAY:US", warehouse: "仓库甲", remaining_quantity: 20 },
      { id: "2", po_code: "PO-UK", site: "AMAZON:RIVMOUNT:UK", warehouse: "仓库乙", remaining_quantity: 15 }
    ]
  };

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(jsonResponse(String(input).endsWith("purchase-options") ? purchases : allocation))
      )
    );
  });

  it("同时展示各站点采购明细与当前文件的分配数量，区分历史和本次", async () => {
    renderDetail(<SelfOperatedExceptionDetails exception={exception} />);
    expect(await screen.findByText("PO-US")).toBeInTheDocument();
    expect(await screen.findByText("PO-UK")).toBeInTheDocument();
    const allocated = within(screen.getByRole("region", { name: "本次入库分配明细" }));
    expect(await allocated.findByText("WV-1")).toBeInTheDocument();
    for (const name of ["关联交货单", "历史已入库", "正常分配", "规则内超收", "本次分配"]) {
      expect(allocated.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(screen.getByLabelText("当前异常数量")).toHaveTextContent("本次申请80正常分配67规则内超收5待处理8");
    expect(screen.queryByRole("button", { name: "保存" })).not.toBeInTheDocument();
  });

  it("采购查询慢或失败时仍展示分配明细，重试只查询采购区域", async () => {
    const pending = deferred<Response>();
    let attempts = 0;
    const fetcher = vi.fn((input: RequestInfo | URL) => {
      if (!String(input).endsWith("purchase-options")) return Promise.resolve(jsonResponse(allocation));
      return ++attempts === 1 ? pending.promise : Promise.resolve(jsonResponse(purchases));
    });
    vi.stubGlobal("fetch", fetcher);
    renderDetail(<SelfOperatedExceptionDetails exception={exception} />);
    expect(await screen.findByText("WV-1")).toBeVisible();
    pending.resolve(jsonResponse({ detail: "采购接口暂时不可用" }, 502));
    expect(await screen.findByText("采购接口暂时不可用")).toBeVisible();
    expect(screen.getByText("WV-1")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "重新查询采购" }));
    expect(await screen.findByText("PO-US")).toBeVisible();
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("inbound-allocation"))).toHaveLength(1);
  });

  it("切换异常后忽略旧响应，不把上一 SKU 的明细显示到当前记录", async () => {
    const old = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        String(input).includes("/30/")
          ? old.promise
          : Promise.resolve(jsonResponse({ ...purchases, ...allocation, items: [] }))
      )
    );
    const { rerender } = renderDetail(<SelfOperatedExceptionDetails exception={exception} />);
    rerender(<SelfOperatedExceptionDetails exception={{ ...exception, id: 31, sku: "SKU-B" }} />);
    expect(await screen.findByText("未查询到该供应商与 SKU 的未交采购明细")).toBeVisible();
    old.resolve(jsonResponse(purchases));
    await waitFor(() => expect(screen.queryByText("PO-US")).not.toBeInTheDocument());
  });

  it("无分配与无采购分别提示，接口文本按普通文字展示", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(
          jsonResponse(
            String(input).endsWith("purchase-options")
              ? { ...purchases, items: [{ ...purchases.items[0], po_code: "<img src=x onerror=alert(1)>" }] }
              : { ...allocation, items: [] }
          )
        )
      )
    );
    const { container } = renderDetail(<SelfOperatedExceptionDetails exception={exception} />);
    expect(await screen.findByText("当前文件的该 SKU 在此站点暂无可入库分配")).toBeVisible();
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });
});
