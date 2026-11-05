import { act, fireEvent, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import { PurchaseSnapshotContext, type BatchPurchaseSnapshotState } from "./useBatchPurchaseSnapshot";
import { useExceptionTransfer } from "./useExceptionTransfer";

const record = createDetailExceptions()[0];
const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const };
const options = {
  sites: [record.full_site],
  purchases: [{ id: "1", po_code: "PO-OLD", site: record.full_site, warehouse: "本地仓", remaining_quantity: 10 }],
  queried_at: "2026-11-04T00:00:00Z",
  purchase_error: null
};

function snapshot(completedAt: string): BatchPurchaseSnapshotState {
  return {
    scope: "7",
    data: {
      state: "ready",
      snapshot_id: "snapshot",
      completed_at: completedAt,
      started_at: null,
      job: null,
      items: [],
      total: 0,
      supplier_count: 1,
      sku_count: 1
    },
    metadata: null,
    loading: false,
    error: null,
    enabled: true,
    index: new Map(),
    refresh: vi.fn()
  };
}

function Selection({ state = null }: { state?: BatchPurchaseSnapshotState | null }) {
  return (
    <PurchaseSnapshotContext value={state}>
      <Transfer />
    </PurchaseSnapshotContext>
  );
}

function Transfer() {
  const transfer = useExceptionTransfer(batch, vi.fn());
  return (
    <>
      <button onClick={() => transfer.rowSelection?.onChange?.([record.id], [record], { type: "single" })}>
        选择记录
      </button>
      {transfer.action}
      {transfer.modal}
    </>
  );
}

function transferRequests() {
  return vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("transfer-options"));
}

async function openSelection() {
  fireEvent.click(screen.getByRole("button", { name: "选择记录" }));
  fireEvent.click(screen.getByRole("button", { name: "转交货批次" }));
  await screen.findByText("PO-OLD");
}

async function closeSelection() {
  fireEvent.click(screen.getByRole("button", { name: /取.*消/ }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

afterEach(() => vi.unstubAllGlobals());

describe("转交选项缓存", () => {
  it("无上下文时取消重开复用缓存，成功后清缓存", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("transfer-options")) return jsonResponse(options);
        if (url.endsWith("preflight")) return jsonResponse({ status: "preflight_ready" });
        return jsonResponse({ id: 44 });
      })
    );
    renderDetail(<Selection />);
    await openSelection();
    await closeSelection();
    fireEvent.click(screen.getByRole("button", { name: "转交货批次" }));
    expect(screen.getByRole("button", { name: "创建交货批次" })).toBeEnabled();
    expect(screen.getByText("PO-OLD")).toBeInTheDocument();
    expect(transferRequests()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "创建交货批次" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await openSelection();
    expect(transferRequests()).toHaveLength(2);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("purchase-options"))).toBe(false);
  });

  it("同一快照保留缓存，完成时间变化后重开重新请求新数据", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(options))
    );
    const { rerender } = renderDetail(<Selection state={snapshot("2026-11-04T00:00:00Z")} />);
    await openSelection();
    await closeSelection();
    rerender(<Selection state={snapshot("2026-11-04T00:00:00Z")} />);
    await openSelection();
    expect(transferRequests()).toHaveLength(1);
    await closeSelection();
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ ...options, purchases: [{ ...options.purchases[0], po_code: "PO-NEW" }] })
    );
    rerender(<Selection state={snapshot("2026-11-04T00:01:00Z")} />);
    fireEvent.click(screen.getByRole("button", { name: "转交货批次" }));
    expect(await screen.findByText("PO-NEW")).toBeInTheDocument();
    expect(screen.queryByText("PO-OLD")).not.toBeInTheDocument();
    expect(transferRequests()).toHaveLength(2);
  });

  it("刷新后不复用在途请求，旧响应不回填缓存或移除新请求", async () => {
    const resolvers: Array<(response: Response) => void> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => resolvers.push(resolve)))
    );
    let state = snapshot("2026-11-04T00:00:00Z");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <PurchaseSnapshotContext value={state}>{children}</PurchaseSnapshotContext>
    );
    const { result, rerender } = renderHook(() => useExceptionTransfer(batch, vi.fn()), { wrapper });
    act(() => result.current.openRow?.(record));
    const load = result.current.modal && result.current.modal.props.loadOptions;
    expect(load).toBeTypeOf("function");
    const oldRequest = load(record.id);
    expect(load(record.id)).toBe(oldRequest);
    state = snapshot("2026-11-04T00:01:00Z");
    rerender();
    const newRequest = load(record.id);
    expect(newRequest).not.toBe(oldRequest);
    resolvers[0](jsonResponse(options));
    await oldRequest;
    expect(load(record.id)).toBe(newRequest);
    const fresh = { ...options, queried_at: "2026-11-04T00:01:00Z" };
    resolvers[1](jsonResponse(fresh));
    await newRequest;
    expect(await load(record.id)).toEqual(fresh);
    expect(transferRequests()).toHaveLength(2);
  });
});
