import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReceiptReview from "./ReceiptReview";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import { createDetailBatch } from "./detailFixtures";
import { renderDetail } from "../batchDetailTestSupport";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";

const fixtureRow: ReceiptRow = {
  file_id: 71,
  filename: "狂飙-A.xlsx",
  supplier: "KuangBiao",
  sku: "SKU-A",
  original_site: "US",
  full_site: "AMAZON:SEEKWAY:US",
  cumulative: 19,
  history: 3,
  requested: 16,
  issue: "",
  candidates: [],
  delivery_numbers: ["LN1"],
  order_numbers: ["WV1"],
  purchase_numbers: ["PO1"],
  item_ids: ["item1"]
};

afterEach(() => vi.unstubAllGlobals());

describe("累计实收核对加载状态", () => {
  function fixture() {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      status: "draft",
      receipt: {
        cumulative_total: 19,
        history_total: 3,
        requested_total: 16,
        issue_count: 0,
        captured_at: "2026-10-29T00:00:00Z"
      }
    };
    const load = vi.fn(async () => null);
    const runAction = async (_name: string, operation: () => Promise<void>) => operation();
    return { batch, load, runAction };
  }

  it("整批采购数据任务运行时仍读取核对明细，不一直加载", async () => {
    const props = fixture();
    const snapshotJob = {
      id: 91,
      batch_id: props.batch.id,
      kind: "purchase_snapshot" as const,
      status: "running",
      attempts: 1,
      error_message: null,
      download_ready: false,
      created_at: "2026-11-04T00:00:00Z",
      claimed_at: "2026-11-04T00:00:00Z",
      heartbeat_at: null,
      finished_at: null
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ items: [fixtureRow], total: 1 }))
    );
    const { container } = renderDetail(
      <ReceiptReview {...props} batch={{ ...props.batch, jobs: { purchase_snapshot: snapshotJob } }} />
    );
    expect(await screen.findByText("狂飙-A.xlsx")).toBeInTheDocument();
    expect(container.querySelector(".ant-spin-spinning")).not.toBeInTheDocument();
  });

  it("请求未返回时批次进入处理中，处理结束后不残留加载状态", async () => {
    const props = fixture();
    const pending = deferred<Response>();
    const fetchMock = vi.fn(() => pending.promise);
    vi.stubGlobal("fetch", fetchMock);
    const { container, rerender } = renderDetail(<ReceiptReview {...props} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const queued = { ...props.batch, status: "queued" };
    rerender(<ReceiptReview {...props} batch={queued} />);
    pending.resolve(jsonResponse({ items: [fixtureRow], total: 1 }));
    fetchMock.mockImplementation(async () => jsonResponse({ items: [fixtureRow], total: 1 }));
    rerender(<ReceiptReview {...props} batch={{ ...queued, status: "draft", updated_at: "2026-11-04T00:00:00Z" }} />);
    expect(await screen.findByText("狂飙-A.xlsx")).toBeInTheDocument();
    await waitFor(() => expect(container.querySelector(".ant-spin-spinning")).not.toBeInTheDocument());
  });
});
