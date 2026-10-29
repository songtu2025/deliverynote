import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReceiptReview from "./ReceiptReview";
import BatchSummary from "./BatchSummary";
import { createDetailBatch } from "./detailFixtures";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";

const fixtureRow = {
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

describe("累计实收核对", () => {
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

  it("显示累计、历史、本次量与逐文件历史依据，明细按页请求", async () => {
    const props = fixture();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ items: [fixtureRow], total: 21 }))
    );
    renderDetail(
      <>
        <BatchSummary batch={props.batch} />
        <ReceiptReview {...props} />
      </>
    );
    expect(await screen.findByText("狂飙-A.xlsx")).toBeInTheDocument();
    const strip = screen.getByText("累计实收", { selector: ".summary-metric span" }).closest(".summary-strip")!;
    expect(within(strip as HTMLElement).getByText("19")).toBeInTheDocument();
    expect(within(strip as HTMLElement).getByText("3")).toBeInTheDocument();
    expect(within(strip as HTMLElement).getByText("16")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看明细" }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("交货单号：LN1")).toBeInTheDocument();
    expect(within(drawer).getByText("入库单：WV1")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByTitle("2"));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("page=2"), expect.anything()));
  });

  it("未知本次量显示待核对，站点选择带文件编号并触发重新核对", async () => {
    const props = fixture();
    const row = {
      ...fixtureRow,
      history: null,
      requested: null,
      issue: "产品信息站点不唯一",
      candidates: ["AMAZON:SEEKWAY:US", "AMAZON:RIVMOUNT:US"]
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown, init?: RequestInit) =>
        init?.method === "PUT" ? jsonResponse(props.batch) : jsonResponse({ items: [row], total: 1 })
      )
    );
    renderDetail(<ReceiptReview {...props} />);
    expect(await screen.findAllByText("待核对")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "查看明细" }));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择该文件的完整站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:RIVMOUNT:US").at(-1)!);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/batches/7/files/71/receipt-site",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ sku: "SKU-A", original_site: "US", full_site: "AMAZON:RIVMOUNT:US" })
        })
      )
    );
    expect(props.load).toHaveBeenCalledWith(true);
  });

  it("有效零历史与零新增正常显示，取数进行中禁止刷新", async () => {
    const props = fixture();
    props.batch.receipt.history_total = 0;
    props.batch.receipt.requested_total = 0;
    props.batch.status = "queued";
    vi.stubGlobal("fetch", vi.fn());
    renderDetail(
      <>
        <BatchSummary batch={props.batch} />
        <ReceiptReview {...props} />
      </>
    );
    expect(screen.getAllByText("0")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "重新取数" })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });
});
