import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReceiptReview from "./ReceiptReview";
import ReceiptReviewDetails from "./ReceiptReviewDetails";
import type { ReceiptRow } from "./ReceiptReviewDetails";
import BatchSummary from "./BatchSummary";
import { createDetailBatch } from "./detailFixtures";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { batchPresentation, batchTaskPresentation } from "./batchPresentation";

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
    expect(screen.queryByRole("switch", { name: "仅显示待核对" })).not.toBeInTheDocument();
    expect(screen.queryByText(/仅显示待核对/)).not.toBeInTheDocument();
    expect(screen.getByText("已核对")).toHaveClass("ant-typography-secondary");
    const summary = within(screen.getByLabelText("入库数量摘要"));
    expect(summary.getByText("19")).toBeInTheDocument();
    expect(summary.getByText("3")).toBeInTheDocument();
    expect(summary.getByText("16")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看明细" }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("交货单号（1）")).toBeInTheDocument();
    expect(within(drawer).getByText("LN1")).toBeInTheDocument();
    expect(within(drawer).getByText("入库单：WV1")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(screen.getAllByTitle("2")).toHaveLength(1);
    fireEvent.click(screen.getByTitle("2"));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("page=2"), expect.anything()));
  });

  it("未确认站点不计待核对，站点选择带文件编号并触发重新核对", async () => {
    const props = fixture();
    props.batch.status = "preflight_ready";
    props.batch.receipt.history_total = 0;
    props.batch.receipt.requested_total = 19;
    expect(batchTaskPresentation(props.batch).title).toBe("预检通过，可以计算");
    const row = {
      ...fixtureRow,
      history: null,
      requested: 19,
      issue: "",
      reason: "产品信息站点不唯一",
      notice: "产品信息站点不唯一：历史未确认，全部进入待处理",
      candidates: ["AMAZON:SEEKWAY:US", "AMAZON:RIVMOUNT:US"]
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: unknown, init?: RequestInit) =>
        init?.method === "PUT" ? jsonResponse(props.batch) : jsonResponse({ items: [row], total: 1 })
      )
    );
    renderDetail(<ReceiptReview {...props} />);
    expect(await screen.findByText("未确认")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "仅显示待核对" })).not.toBeInTheDocument();
    expect(screen.getByText(row.notice)).toHaveClass("ant-typography-warning");
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
    expect(screen.queryByRole("button", { name: "同步积加入库记录" })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("问题清零后隐藏开关并复位筛选和页码", async () => {
    const props = fixture();
    props.batch.receipt.issue_count = 21;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ items: [fixtureRow], total: 21 }))
    );
    const { rerender } = renderDetail(<ReceiptReview {...props} />);
    await screen.findByText("已核对");
    fireEvent.click(screen.getByRole("switch", { name: "仅显示待核对" }));
    fireEvent.click(screen.getByTitle("2"));
    await waitFor(() =>
      expect(fetch).toHaveBeenLastCalledWith(
        expect.stringContaining("page=2&page_size=20&issues_only=true"),
        expect.anything()
      )
    );
    rerender(
      <ReceiptReview {...props} batch={{ ...props.batch, receipt: { ...props.batch.receipt, issue_count: 0 } }} />
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenLastCalledWith(
        expect.stringContaining("page=1&page_size=20&issues_only=false"),
        expect.anything()
      )
    );
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByText(/仅显示待核对/)).not.toBeInTheDocument();
    expect(screen.getByText("已核对")).toBeInTheDocument();
  });

  it("未匹配明细显示转待处理提示，允许继续计算", async () => {
    const props = fixture();
    props.batch.status = "preflight_ready";
    const row = {
      ...fixtureRow,
      history: 0,
      requested: 19,
      notice: "未匹配到入库明细，该数量将进入待处理",
      order_numbers: [],
      purchase_numbers: [],
      item_ids: [],
      entries: []
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ items: [row], total: 1 }))
    );
    renderDetail(<ReceiptReview {...props} />);
    expect(batchPresentation(props.batch).canCompute).toBe(true);
    expect(await screen.findByText(row.notice)).toHaveClass("ant-typography-warning");
    expect(screen.queryByText("已核对")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看明细" }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText(row.notice)).toBeInTheDocument();
    expect(within(drawer).getByText("入库单：未匹配")).toBeInTheDocument();
  });
});

describe("累计数量与历史依据抽屉", () => {
  function renderDrawer(overrides: Partial<ReceiptRow> = {}, busy = false) {
    const target = { ...fixtureRow, ...overrides };
    const onChooseSite = vi.fn(async () => undefined);
    renderDetail(<ReceiptReviewDetails target={target} busy={busy} onClose={vi.fn()} onChooseSite={onChooseSite} />);
    return { target, onChooseSite };
  }

  const entries = ["COMPLETED", "PART_INBOUND", "WAIT_INBOUND", "OTHER"].map((status, index) => ({
    item_id: `item${index}`,
    order_no: `WV${index}`,
    purchase_no: `PO${index}`,
    status,
    history: index,
    shelf_numbers: index === 0 ? "S1、S2" : ""
  }));

  it("显示中文状态、次行 ID 和分批单号及合计，省去重复依据和横向滚动", () => {
    renderDrawer({ entries });
    expect(screen.getByRole("heading", { name: "SKU-A · US" })).toBeInTheDocument();
    const history = within(screen.getByRole("region", { name: "历史入库明细" }));
    expect(history.getByText("ID item0 · 分批 S1、S2")).toBeInTheDocument();
    expect(history.getByText("ID item1")).toBeInTheDocument();
    for (const status of ["已完结", "部分入库", "待入库", "OTHER"]) {
      expect(history.getByText(status)).toBeInTheDocument();
    }
    expect(history.getByRole("row", { name: "合计 6" })).toBeInTheDocument();
    expect(history.getAllByRole("columnheader")).toHaveLength(4);
    expect(history.getByRole("table").parentElement).not.toHaveStyle({ overflowX: "auto" });
    expect(history.getByRole("table")).not.toHaveStyle({ minWidth: "650px" });
    expect(screen.queryByText("入库单：WV1")).not.toBeInTheDocument();
    expect(screen.queryByText("采购单：PO1")).not.toBeInTheDocument();
    expect(screen.queryByText("积加商品明细 ID：item1")).not.toBeInTheDocument();
  });

  it("任一历史数量未知时，明细和合计均显示待核对", () => {
    renderDrawer({ entries: [{ ...entries[0], history: null }, entries[1]], history: null, requested: null });
    const history = within(screen.getByRole("region", { name: "历史入库明细" }));
    expect(history.getByRole("row", { name: "合计 待核对" })).toBeInTheDocument();
    expect(history.getAllByText("待核对")).toHaveLength(2);
    expect(within(screen.getByLabelText("入库数量算式")).getAllByText("待核对")).toHaveLength(2);
  });

  it.each([undefined, []])("entries 为 %s 时使用原有三行依据兜底", (emptyEntries) => {
    renderDrawer({ entries: emptyEntries, order_numbers: [], purchase_numbers: [], item_ids: [] });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    for (const label of ["入库单", "采购单", "积加商品明细 ID"]) {
      expect(screen.getByText(`${label}：尚未确认`)).toBeInTheDocument();
    }
  });

  it("未匹配且没有交货单号时保留提示和三行未匹配，不显示交货单区块", () => {
    const notice = "未匹配到入库明细，该数量将进入待处理";
    renderDrawer({ notice, entries: [], order_numbers: [], purchase_numbers: [], item_ids: [], delivery_numbers: [] });
    expect(screen.getByRole("alert")).toHaveTextContent(notice);
    for (const label of ["入库单", "采购单", "积加商品明细 ID"]) {
      expect(screen.getByText(`${label}：未匹配`)).toBeInTheDocument();
    }
    expect(screen.queryByRole("region", { name: "交货单号" })).not.toBeInTheDocument();
  });

  it("显示单号数量并复制全部单号，特殊字符按文本呈现", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", Object.create(navigator, { clipboard: { value: { writeText } } }));
    const deliveryNumbers = ["LN1", "LN2", "<img src=x onerror=alert(1)>"];
    renderDrawer({ delivery_numbers: deliveryNumbers });
    const deliveries = within(screen.getByRole("region", { name: "交货单号" }));
    expect(deliveries.getByRole("heading", { name: "交货单号（3）" })).toBeInTheDocument();
    expect(deliveries.getByText(deliveryNumbers.join("、"))).toBeInTheDocument();
    expect(deliveries.queryByRole("img", { name: "" })).not.toBeInTheDocument();
    fireEvent.click(deliveries.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(deliveryNumbers.join("、")));
  });

  it("站点选择仍调用原回调", () => {
    const { target, onChooseSite } = renderDrawer({
      issue: "产品信息站点不唯一",
      candidates: ["AMAZON:SEEKWAY:US", "AMAZON:RIVMOUNT:US"]
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择该文件的完整站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:RIVMOUNT:US").at(-1)!);
    expect(onChooseSite).toHaveBeenCalledWith(target, "AMAZON:RIVMOUNT:US");
  });

  it("处理期间禁用站点选择", () => {
    renderDrawer({ issue: "产品信息站点不唯一", candidates: ["US", "UK"] }, true);
    expect(screen.getByRole("combobox", { name: "选择该文件的完整站点" })).toBeDisabled();
  });

  it.each([
    { issue: "", candidates: ["US", "UK"] },
    { issue: "站点未确认", candidates: ["US"] }
  ])("不满足原条件时不显示站点选择器：%s", (overrides) => {
    renderDrawer(overrides);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
