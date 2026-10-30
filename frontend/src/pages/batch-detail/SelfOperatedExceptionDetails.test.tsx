import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions, fixtureJob } from "./detailFixtures";
import SelfOperatedExceptionDetails from "./SelfOperatedExceptionDetails";
import BatchPurchaseSnapshot, { BatchPurchaseSnapshotNotice } from "./BatchPurchaseSnapshot";

describe("自营仓异常依据", () => {
  const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const };
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
    state: "ready",
    snapshot_id: "snapshot-1",
    started_at: "2026-10-30T00:59:00Z",
    completed_at: "2026-10-30T01:00:00Z",
    supplier_count: 1,
    sku_count: 1,
    total: 2,
    job: fixtureJob({ kind: "purchase_snapshot", status: "succeeded" }),
    items: [
      {
        id: "1",
        supplier_code: "GYS-023",
        sku: exception.sku,
        po_code: "PO-US",
        site: "AMAZON:SEEKWAY:US",
        warehouse: "仓库甲",
        remaining_quantity: 20
      },
      {
        id: "2",
        supplier_code: "GYS-023",
        sku: exception.sku,
        po_code: "PO-UK",
        site: "AMAZON:RIVMOUNT:UK",
        warehouse: "仓库乙",
        remaining_quantity: 15
      }
    ]
  };
  const detail = (record = exception) => (
    <BatchPurchaseSnapshot batch={batch}>
      <BatchPurchaseSnapshotNotice />
      <SelfOperatedExceptionDetails exception={record} supplierCode="GYS-023" />
    </BatchPurchaseSnapshot>
  );

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(jsonResponse(String(input).includes("purchase-snapshot") ? purchases : allocation))
      )
    );
  });

  it("同时展示各站点采购快照和当前文件分配，移除逐行采购刷新", async () => {
    renderDetail(detail());
    expect(await screen.findByText("PO-US")).toBeInTheDocument();
    expect(await screen.findByText("PO-UK")).toBeInTheDocument();
    const allocated = within(screen.getByRole("region", { name: "本次入库分配明细" }));
    expect(await allocated.findByText("WV-1")).toBeInTheDocument();
    for (const name of ["关联交货单", "历史已入库", "正常分配", "规则内超收", "本次分配"]) {
      expect(allocated.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(screen.getByLabelText("当前异常数量")).toHaveTextContent("本次申请80正常分配67规则内超收5待处理8");
    expect(screen.queryByRole("button", { name: "保存" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重新查询采购" })).not.toBeInTheDocument();
  });

  it("整批采购慢或失败不阻塞分配，用户可以主动重试整批", async () => {
    const pending = deferred<Response>();
    let attempts = 0;
    const fetcher = vi.fn((input: RequestInfo | URL) => {
      if (!String(input).includes("purchase-snapshot")) return Promise.resolve(jsonResponse(allocation));
      return ++attempts === 1 ? pending.promise : Promise.resolve(jsonResponse(purchases));
    });
    vi.stubGlobal("fetch", fetcher);
    renderDetail(detail());
    expect(await screen.findByText("WV-1")).toBeVisible();
    pending.resolve(jsonResponse({ detail: "采购接口暂时不可用" }, 502));
    expect((await screen.findAllByText("采购接口暂时不可用"))[0]).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "重试整批采购数据" }));
    expect(await screen.findByText("PO-US")).toBeVisible();
    expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("inbound-allocation"))).toHaveLength(1);
  });

  it("切换异常不再查询采购，并忽略上一条分配的迟到响应", async () => {
    const old = deferred<Response>();
    const fetcher = vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("purchase-snapshot")) return Promise.resolve(jsonResponse(purchases));
      return String(input).includes("/30/") ? old.promise : Promise.resolve(jsonResponse({ ...allocation, items: [] }));
    });
    vi.stubGlobal("fetch", fetcher);
    const { rerender } = renderDetail(detail());
    expect(await screen.findByText("PO-US")).toBeVisible();
    rerender(detail({ ...exception, id: 31, sku: "SKU-B" }));
    expect(await screen.findByText("未查询到该供应商与 SKU 的未交采购明细")).toBeVisible();
    old.resolve(jsonResponse(allocation));
    await waitFor(() => expect(screen.queryByText("WV-1")).not.toBeInTheDocument());
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("purchase-snapshot"))).toHaveLength(1);
  });

  it("空分配有独立提示，采购接口文本按普通文字展示", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(
          jsonResponse(
            String(input).includes("purchase-snapshot")
              ? { ...purchases, total: 1, items: [{ ...purchases.items[0], po_code: "<img src=x onerror=alert(1)>" }] }
              : { ...allocation, items: [] }
          )
        )
      )
    );
    const { container } = renderDetail(detail());
    expect(await screen.findByText("当前文件的该 SKU 在此站点暂无可入库分配")).toBeVisible();
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });
});
