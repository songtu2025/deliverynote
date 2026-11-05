import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import InboundAllocationEditor from "./InboundAllocationEditor";
import type { InboundAllocations } from "../../inboundExceptionApi";

const exception = { ...createDetailExceptions()[3], manual_quantity: 8 };
const row = {
  id: "1",
  po_code: "PO-1",
  inbound_no: "WV-1",
  delivery_no: "LN-1",
  site: exception.full_site,
  warehouse: "合成仓",
  history_quantity: 0,
  normal_quantity: 10,
  overreceipt_quantity: 0,
  current_quantity: 12,
  max_receive_quantity: 12,
  received_quantity: 0,
  extra_quantity: 2,
  extra_reason: "确认",
  targeted_quantity: 2
};
const data: InboundAllocations = {
  batch_id: 7,
  supplier_code: "GYS-023",
  batch_updated_at: "2026-11-05T00:00:00Z",
  history_captured_at: null,
  allowance_limit: 10,
  recompute_disabled_reason: null,
  items: [
    row,
    {
      ...row,
      id: "2",
      po_code: "PO-2",
      inbound_no: "WV-2",
      extra_quantity: 0,
      extra_reason: "",
      current_quantity: 1,
      targeted_quantity: 0
    }
  ],
  saved_allowances: [],
  inactive_allowances: []
};
afterEach(() => vi.unstubAllGlobals());
beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

describe("指定 PO 追加超收", () => {
  it("显示已保存数量，有改动才可保存，合计不能超过上限", () => {
    renderDetail(<InboundAllocationEditor data={data} exception={exception} />);
    const submit = screen.getByRole("button", { name: "保存并重算" });
    expect(submit).toBeDisabled();
    const first = screen.getByRole("spinbutton", { name: "追加超收 PO-1 WV-1" });
    expect(first).toHaveValue("2");
    fireEvent.change(first, { target: { value: "5" } });
    expect(submit).toBeEnabled();
    expect(screen.getByText("超出最大可收货，积加可能拒收")).toBeVisible();
    fireEvent.change(screen.getByRole("spinbutton", { name: "追加超收 PO-2 WV-2" }), { target: { value: "6" } });
    expect(screen.getByRole("alert")).toHaveTextContent("合计追加不得超过 10");
    expect(submit).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("原因可选，保存只发一次统一调整请求", async () => {
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pending.promise)
    );
    const saved = vi.fn(async () => undefined);
    renderDetail(<InboundAllocationEditor data={data} exception={exception} onSaved={saved} />);
    fireEvent.change(screen.getByRole("spinbutton", { name: "追加超收 PO-1 WV-1" }), { target: { value: "4" } });
    fireEvent.change(screen.getByRole("textbox", { name: "原因" }), { target: { value: "新原因" } });
    const submit = screen.getByRole("button", { name: "保存并重算" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(fetch).toHaveBeenCalledOnce();
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/batches/7/adjustments");
    expect(JSON.parse(options?.body as string)).toEqual({
      allowances: [
        {
          supplier_code: "GYS-023",
          sku: exception.sku,
          full_site: exception.full_site,
          file_id: exception.batch_file_id,
          inbound_no: "WV-1",
          po_code: "PO-1",
          quantity: 4,
          reason: "新原因"
        }
      ],
      sites: []
    });
    pending.resolve(jsonResponse(createDetailBatch()));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  });

  it("未生效有提示，任务或转交关联禁用输入与保存", () => {
    renderDetail(
      <InboundAllocationEditor
        data={{
          ...data,
          recompute_disabled_reason: "批次已有转交记录",
          inactive_allowances: [
            {
              supplier_code: "GYS-023",
              sku: exception.sku,
              full_site: "旧站点",
              inbound_no: "WV-X",
              po_code: "PO-X",
              quantity: 4,
              reason: ""
            }
          ]
        }}
        exception={exception}
      />
    );
    expect(screen.getByText(/指定的 PO 本次无分配，追加未生效/)).toBeVisible();
    expect(screen.getByText("批次已有转交记录")).toBeVisible();
    for (const input of screen.getAllByRole("spinbutton")) expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存并重算" })).toBeDisabled();
  });

  it("保存失败保留输入；填 0 撤销也可保存", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "输入已变化" }, 400))
    );
    renderDetail(<InboundAllocationEditor data={data} exception={exception} />);
    const first = screen.getByRole("spinbutton", { name: "追加超收 PO-1 WV-1" });
    fireEvent.change(first, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并重算" }));
    expect(await screen.findByText("输入已变化")).toBeVisible();
    expect(first).toHaveValue("0");
  });
});
