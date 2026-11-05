import { beforeEach, describe, expect, it, vi } from "vitest";
import { beginPurchaseSnapshot, readCompletePurchaseSnapshot, type PurchaseSnapshot } from "./inboundExceptionApi";
import { fixtureJob } from "./pages/batch-detail/detailFixtures";
import { jsonResponse } from "./pages/admin/positionDraftTestSupport";

describe("整批采购快照请求", () => {
  const first: PurchaseSnapshot = {
    state: "ready",
    job: fixtureJob({ kind: "purchase_snapshot", status: "succeeded" }),
    snapshot_id: "version-1",
    started_at: "2026-10-30T00:00:00Z",
    completed_at: "2026-10-30T00:01:00Z",
    supplier_count: 1,
    sku_count: 1,
    total: 1,
    items: [
      {
        id: "1",
        supplier_code: "GYS-1",
        sku: "SKU-A",
        po_code: "PO-1",
        site: "AMAZON:SEEKWAY:US",
        warehouse: "仓库甲",
        remaining_quantity: 8
      }
    ]
  };
  beforeEach(() =>
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse(first)))
    )
  );

  it("已有快照或失败任务时仅读取，首次才发起任务", async () => {
    const fetcher = vi.mocked(fetch);
    await beginPurchaseSnapshot(7, false, new AbortController().signal);
    expect(fetcher).toHaveBeenCalledTimes(1);
    fetcher.mockClear();
    fetcher.mockResolvedValueOnce(jsonResponse({ ...first, state: "missing", job: null, items: [] }));
    await beginPurchaseSnapshot(7, false, new AbortController().signal);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify({ refresh: false }) });
    fetcher.mockClear();
    fetcher.mockResolvedValue(jsonResponse({ ...first, job: { ...first.job, status: "failed" } }));
    await beginPurchaseSnapshot(7, false, new AbortController().signal);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("固定版本读取所有分页，超过首屏的数据也能使用", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ...first, items: [{ ...first.items[0], id: "201" }] }));
    const page = {
      ...first,
      total: 201,
      items: Array.from({ length: 200 }, (_, id) => ({ ...first.items[0], id: String(id) }))
    };
    const result = await readCompletePurchaseSnapshot(7, page, new AbortController().signal);
    expect(result.items).toHaveLength(201);
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain("snapshot_id=version-1&offset=200&limit=200");
  });

  it("分页期间版本变化时重新读取，不混合两份快照", async () => {
    const newer = { ...first, snapshot_id: "version-2", items: [{ ...first.items[0], po_code: "PO-NEW" }] };
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: "快照已更新" }, 409))
      .mockResolvedValueOnce(jsonResponse(newer));
    const result = await readCompletePurchaseSnapshot(7, { ...first, total: 2 }, new AbortController().signal);
    expect(result.snapshot_id).toBe("version-2");
    expect(result.items.map(({ po_code }) => po_code)).toEqual(["PO-NEW"]);
  });

  it("不完整分页不能返回成功结果，离开页面后不能补发首次任务", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ ...first, items: [] }));
    await expect(readCompletePurchaseSnapshot(7, { ...first, total: 2 }, new AbortController().signal)).rejects.toThrow(
      "分页不完整"
    );
    const controller = new AbortController();
    vi.mocked(fetch)
      .mockClear()
      .mockImplementationOnce(async () => {
        controller.abort();
        return jsonResponse({ ...first, job: null });
      });
    await expect(beginPurchaseSnapshot(7, false, controller.signal)).rejects.toThrow();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
