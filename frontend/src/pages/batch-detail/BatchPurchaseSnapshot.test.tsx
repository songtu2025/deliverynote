import { useState } from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions, fixtureJob } from "./detailFixtures";
import BatchPurchaseSnapshot, { BatchPurchaseSnapshotNotice } from "./BatchPurchaseSnapshot";
import SelfOperatedExceptionDetails from "./SelfOperatedExceptionDetails";

const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const };
const ready = {
  state: "ready",
  job: fixtureJob({ kind: "purchase_snapshot", status: "succeeded" }),
  snapshot_id: "version-1",
  started_at: "2026-10-30T00:00:00Z",
  completed_at: "2026-10-30T00:01:00Z",
  supplier_count: 1,
  sku_count: 2,
  total: 2,
  items: ["SKU-A", "SKU-B"].map((sku) => ({
    id: sku,
    supplier_code: "GYS-023",
    sku,
    po_code: `PO-${sku}`,
    site: "AMAZON:SEEKWAY:US",
    warehouse: "仓库甲",
    remaining_quantity: 8
  }))
};

function Workbench() {
  const [sku, setSku] = useState("SKU-A");
  const [open, setOpen] = useState(true);
  return (
    <BatchPurchaseSnapshot batch={batch}>
      <BatchPurchaseSnapshotNotice />
      <button onClick={() => setSku("SKU-B")}>切换 SKU</button>
      <button onClick={() => setOpen((value) => !value)}>开关详情</button>
      {open && (
        <SelfOperatedExceptionDetails exception={{ ...createDetailExceptions()[0], sku }} supplierCode="GYS-023" />
      )}
    </BatchPurchaseSnapshot>
  );
}

describe("整批采购快照工作区", () => {
  it("首次仅创建一次任务，切换和重开详情不查询，重进页面只读已保存快照", async () => {
    let exists = false;
    const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).includes("purchase-snapshot")) return Promise.resolve(jsonResponse({ items: [] }));
      if (init?.method === "POST") {
        exists = true;
        return Promise.resolve(
          jsonResponse({ ...ready, state: "missing", items: [], job: { ...ready.job, status: "queued" } })
        );
      }
      return Promise.resolve(jsonResponse(exists ? ready : { ...ready, state: "missing", items: [], job: null }));
    });
    vi.stubGlobal("fetch", fetcher);
    const { unmount } = renderDetail(<Workbench />);
    expect(await screen.findByText("PO-SKU-A", {}, { timeout: 4000 })).toBeVisible();
    const count = fetcher.mock.calls.filter(([url]) => String(url).includes("purchase-snapshot")).length;
    fireEvent.click(screen.getByRole("button", { name: "切换 SKU" }));
    expect(await screen.findByText("PO-SKU-B")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "开关详情" }));
    fireEvent.click(screen.getByRole("button", { name: "开关详情" }));
    expect(await screen.findByText("PO-SKU-B")).toBeVisible();
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("purchase-snapshot"))).toHaveLength(count);
    unmount();
    renderDetail(<Workbench />);
    expect(await screen.findByText("PO-SKU-A")).toBeVisible();
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("刷新失败保留旧快照，显式重试成功后统一使用新版本", async () => {
    let attempts = 0;
    const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).includes("purchase-snapshot")) return Promise.resolve(jsonResponse({ items: [] }));
      if (init?.method !== "POST") return Promise.resolve(jsonResponse(ready));
      attempts += 1;
      return Promise.resolve(
        jsonResponse(
          attempts === 1
            ? { ...ready, job: { ...ready.job, status: "failed", error_message: "整批刷新失败，旧结果保留" } }
            : {
                ...ready,
                snapshot_id: "version-2",
                items: ready.items.map((row) => ({ ...row, po_code: `NEW-${row.sku}` }))
              }
        )
      );
    });
    vi.stubGlobal("fetch", fetcher);
    renderDetail(<Workbench />);
    expect(await screen.findByText("PO-SKU-A")).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "刷新整批采购数据" }));
    expect(await screen.findByText("整批刷新失败，旧结果保留")).toBeVisible();
    expect(screen.getByText("PO-SKU-A")).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "重试整批采购数据" }));
    expect(await screen.findByText("NEW-SKU-A")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "切换 SKU" }));
    expect(await screen.findByText("NEW-SKU-B")).toBeVisible();
    await waitFor(() => expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2));
    for (const [, init] of fetcher.mock.calls.filter(([, init]) => init?.method === "POST")) {
      expect(init?.body).toBe(JSON.stringify({ refresh: true }));
    }
  });
});
