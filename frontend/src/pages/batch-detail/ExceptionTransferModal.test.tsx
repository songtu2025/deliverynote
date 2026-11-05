import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Table } from "antd";
import type { DeliveryException } from "../../types";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import ExceptionTransferModal from "./ExceptionTransferModal";
import ExceptionTransfers from "./ExceptionTransfers";
import { useExceptionTransfer } from "./useExceptionTransfer";
import { getTransferOptions } from "../../exceptionTransferApi";

const record = { ...createDetailExceptions()[0], manual_quantity: 8, transferred_quantity: 3 };
const records = [record];
const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const };

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("transfer-options"))
        return jsonResponse({
          sites: ["AMAZON:SEEKWAY:US", "AMAZON:OTHER:US", "AMAZON:EMPTY:DE"],
          purchases: [
            { id: "1", po_code: "PO-US", warehouse: "本地仓", site: "AMAZON:SEEKWAY:US", remaining_quantity: 5 },
            { id: "2", po_code: "PO-OTHER", warehouse: "广州仓", site: "AMAZON:OTHER:US", remaining_quantity: 7 },
            { id: "3", po_code: "PO-OTHER-2", warehouse: "广州仓", site: "AMAZON:OTHER:US", remaining_quantity: 5 }
          ],
          queried_at: "2026-11-04T00:00:00Z",
          purchase_error: null
        });
      if (url.endsWith("preflight")) return jsonResponse({ status: "preflight_ready" });
      return jsonResponse({ id: 44 });
    })
  );
});
afterEach(() => vi.unstubAllGlobals());

function Selection({ onSuccess }: { onSuccess: (id: number) => void }) {
  const transfer = useExceptionTransfer(batch, onSuccess);
  return (
    <>
      {transfer.action}
      <Table<DeliveryException>
        rowKey="id"
        pagination={false}
        rowSelection={transfer.rowSelection}
        dataSource={[record, { ...record, id: 31, status: "resolved" }]}
        columns={[{ title: "SKU", dataIndex: "sku" }]}
      />
      {transfer.modal}
    </>
  );
}

function renderModal(modalRecords = records) {
  return renderDetail(
    <ExceptionTransferModal
      batchId={7}
      records={modalRecords}
      optionsCache={new Map()}
      loadOptions={getTransferOptions}
      onClose={vi.fn()}
      onSuccess={vi.fn()}
    />
  );
}

async function openSelection() {
  fireEvent.click(screen.getAllByRole("checkbox")[1]);
  fireEvent.click(screen.getByRole("button", { name: "转交货批次" }));
  await screen.findByText("PO-US");
}

async function submitAndExpectNavigation(onSuccess: ReturnType<typeof vi.fn>) {
  fireEvent.click(screen.getByRole("button", { name: "创建交货批次" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(44));
}

describe("自营仓转交货", () => {
  it("勾选后打开弹窗，默认剩余量与原站点，换站点提交并跳转", async () => {
    const onSuccess = vi.fn();
    renderDetail(<Selection onSuccess={onSuccess} />);
    expect(screen.queryByRole("button", { name: "转交货批次" })).not.toBeInTheDocument();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes[2]).toBeDisabled();
    fireEvent.click(boxes[1]);
    expect(screen.getByText("已选 1 条")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "转交货批次" }));
    const quantity = await screen.findByRole("spinbutton", { name: "SKU-A 转交数量" });
    expect(quantity).toHaveValue("5");
    await waitFor(() => expect(screen.getByRole("button", { name: "创建交货批次" })).toBeEnabled());
    expect(screen.getByRole("combobox", { name: "SKU-A 目标站点" }).closest(".ant-select")).toHaveTextContent(
      "SEEKWAY:US · 未交 5"
    );
    expect(screen.getByText("PO-US")).toBeInTheDocument();
    expect(screen.queryByText("PO-OTHER")).not.toBeInTheDocument();
    expect(screen.getByText(/采购数据时间/)).toBeInTheDocument();
    fireEvent.change(quantity, { target: { value: "2" } });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "SKU-A 目标站点" }));
    fireEvent.click(await screen.findByText("OTHER:US · 未交 12"));
    expect(await screen.findByText("PO-OTHER")).toBeInTheDocument();
    expect(screen.queryByText("PO-US")).not.toBeInTheDocument();
    await submitAndExpectNavigation(onSuccess);
    expect(
      vi
        .mocked(fetch)
        .mock.calls.map(([url]) => String(url))
        .slice(-3)
    ).toEqual([
      "/api/batches/7/exceptions/transfer-to-delivery",
      "/api/batches/44/preflight",
      "/api/batches/44/compute"
    ]);
    expect(screen.getByText("已创建交货批次 #44 并开始计算")).toBeInTheDocument();
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("transfer-to-delivery"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      items: [{ exception_id: record.id, quantity: 2, full_site: "AMAZON:OTHER:US" }]
    });
  });

  it.each(["0", "-1", "6", "1.5"])("拒绝无效数量 %s，不提交请求", async (value) => {
    renderModal();
    await waitFor(() => expect(screen.getByRole("button", { name: "创建交货批次" })).toBeEnabled());
    fireEvent.change(screen.getByRole("spinbutton", { name: "SKU-A 转交数量" }), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "创建交货批次" }));
    expect(await screen.findByText("请输入剩余量以内的正整数")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("transfer-to-delivery"))).toBe(false);
  });

  it("提交冲突保留输入，取消不发送转交请求", async () => {
    const previous = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("transfer-to-delivery")
          ? Promise.resolve(new Response(JSON.stringify({ detail: "剩余可转量已变化" }), { status: 400 }))
          : previous(input, init)
      )
    );
    const onClose = vi.fn();
    renderDetail(
      <ExceptionTransferModal
        batchId={7}
        records={records}
        optionsCache={new Map()}
        loadOptions={getTransferOptions}
        onClose={onClose}
        onSuccess={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "创建交货批次" })).toBeEnabled());
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "创建交货批次" }));
    expect(await screen.findByText("剩余可转量已变化")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton")).toHaveValue("2");
    fireEvent.click(screen.getByRole("button", { name: /取.*消/ }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("transfer-to-delivery"))).toHaveLength(1);
  });

  it("转交历史显示数量并链接交货批次", () => {
    renderDetail(
      <ExceptionTransfers
        record={{ ...record, transfers: [{ target_batch_id: 44, quantity: 3, full_site: "AMAZON:OTHER:US" }] }}
      />
    );
    expect(screen.getByRole("link", { name: "已转 3 件 → 交货批次 #44" })).toHaveAttribute("href", "/batches/44");
  });

  it("同 SKU 同站点按行顺序扣减，数量与站点变化时重算结论和合计", async () => {
    renderModal([record, { ...record, id: 99 }, { ...record, id: 100 }]);
    await screen.findAllByText("PO-US");
    const rows = screen.getAllByRole("row").filter((row) => within(row).queryByRole("spinbutton"));
    expect(within(rows[0]).getByText("全部可扣")).toBeInTheDocument();
    expect(within(rows[1]).getByText("5 件进待处理")).toBeInTheDocument();
    expect(within(rows[2]).getByText("5 件进待处理")).toBeInTheDocument();
    expect(screen.getByText("合计转交 15 件 = 预计可扣 5 + 预计待处理 10")).toBeInTheDocument();
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "2" } });
    expect(await within(rows[1]).findByText("可扣 3，2 件进待处理")).toBeInTheDocument();
    expect(screen.getByText("合计转交 12 件 = 预计可扣 5 + 预计待处理 7")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getAllByRole("combobox")[0]);
    fireEvent.click(await screen.findByText("OTHER:US · 未交 12"));
    expect(await within(rows[0]).findByText("PO-OTHER")).toBeInTheDocument();
    expect(within(rows[1]).getByText("全部可扣")).toBeInTheDocument();
    expect(within(rows[2]).getByText("5 件进待处理")).toBeInTheDocument();
    expect(screen.getByText("合计转交 12 件 = 预计可扣 7 + 预计待处理 5")).toBeInTheDocument();
    for (const row of rows) expect(within(row).queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Expand row|Collapse row/ })).not.toBeInTheDocument();
  });

  it("不同 SKU 独立扣减，清空数量时不计入转交合计", async () => {
    renderModal([record, { ...record, id: 99, sku: "SKU-B" }]);
    await screen.findAllByText("PO-US");
    expect(screen.getAllByText("全部可扣")).toHaveLength(2);
    expect(screen.getByText("合计转交 10 件 = 预计可扣 10 + 预计待处理 0")).toBeInTheDocument();
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "" } });
    expect(await screen.findByText("合计转交 5 件 = 预计可扣 5 + 预计待处理 0")).toBeInTheDocument();
  });

  it.each(["preflight_failed", "request_failed", "compute_failed"])("%s 仍跳转", async (failure) => {
    const previous = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("preflight") && failure !== "compute_failed")
          return Promise.resolve(
            failure === "request_failed"
              ? new Response(JSON.stringify({ detail: "预检请求失败" }), { status: 500 })
              : jsonResponse({ status: "preflight_failed" })
          );
        if (url.endsWith("compute"))
          return Promise.resolve(new Response(JSON.stringify({ detail: "启动失败" }), { status: 500 }));
        return previous(input, init);
      })
    );
    const onSuccess = vi.fn();
    renderDetail(<Selection onSuccess={onSuccess} />);
    await openSelection();
    await submitAndExpectNavigation(onSuccess);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("compute"))).toBe(
      failure === "compute_failed"
    );
    // 提示由 message 异步渲染，需等待出现，避免偶发失败。
    expect(
      await screen.findByText(new RegExp(failure === "compute_failed" ? "计算启动失败" : "预检未通过"))
    ).toBeInTheDocument();
  });

  it("采购快照不可用时显示原因，仍允许选择站点提交", async () => {
    const purchaseError = "请先加载或刷新整批采购数据";
    const data = {
      sites: [record.full_site],
      purchases: [],
      queried_at: null,
      purchase_error: purchaseError
    };
    renderDetail(
      <ExceptionTransferModal
        batchId={7}
        records={records}
        optionsCache={new Map([[record.id, data]])}
        loadOptions={async () => data}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );
    expect(await screen.findByText(purchaseError)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建交货批次" })).toBeEnabled();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("合计转交 5 件 = 预计可扣 — + 预计待处理 —")).toBeInTheDocument();
  });
});
