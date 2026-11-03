import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Table } from "antd";
import type { DeliveryException } from "../../types";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import ExceptionTransferModal from "./ExceptionTransferModal";
import ExceptionTransfers from "./ExceptionTransfers";
import { useExceptionTransfer } from "./useExceptionTransfer";

const record = { ...createDetailExceptions()[0], manual_quantity: 8, transferred_quantity: 3 };
const records = [record];
const batch = { ...createDetailBatch(), workflow: "self_operated_inbound" as const };

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("transfer-options")) return jsonResponse({ sites: ["AMAZON:SEEKWAY:US", "AMAZON:OTHER:US"] });
      if (url.endsWith("purchase-options"))
        return jsonResponse({
          items: [
            { site: "AMAZON:SEEKWAY:US", remaining_quantity: 5 },
            { site: "AMAZON:OTHER:US", remaining_quantity: 7 },
            { site: "AMAZON:OTHER:US", remaining_quantity: 5 }
          ]
        });
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

describe("自营仓转交货", () => {
  it("勾选后打开弹窗，默认剩余量与原站点，换站点提交并跳转", async () => {
    const onSuccess = vi.fn();
    renderDetail(<Selection onSuccess={onSuccess} />);
    const transfer = screen.getByRole("button", { name: "转交货批次" });
    expect(transfer).toBeDisabled();
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes[2]).toBeDisabled();
    fireEvent.click(boxes[1]);
    expect(screen.getByText("已选 1 条")).toBeInTheDocument();
    fireEvent.click(transfer);
    const quantity = await screen.findByRole("spinbutton", { name: "SKU-A 转交数量" });
    expect(quantity).toHaveValue("5");
    await waitFor(() => expect(screen.getByRole("button", { name: "创建交货批次" })).toBeEnabled());
    expect(screen.getByRole("combobox", { name: "SKU-A 目标站点" }).closest(".ant-select")).toHaveTextContent(
      "AMAZON:SEEKWAY:US"
    );
    fireEvent.change(quantity, { target: { value: "2" } });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "SKU-A 目标站点" }));
    fireEvent.click(await screen.findByText("AMAZON:OTHER:US（未交 12 件）"));
    fireEvent.click(screen.getByRole("button", { name: "创建交货批次" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(44));
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("transfer-to-delivery"));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      items: [{ exception_id: record.id, quantity: 2, full_site: "AMAZON:OTHER:US" }]
    });
  });

  it.each(["0", "-1", "6", "1.5"])("拒绝无效数量 %s，不提交请求", async (value) => {
    renderDetail(<ExceptionTransferModal batchId={7} records={records} onClose={vi.fn()} onSuccess={vi.fn()} />);
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
    renderDetail(<ExceptionTransferModal batchId={7} records={records} onClose={onClose} onSuccess={vi.fn()} />);
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
});
