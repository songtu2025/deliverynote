import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Batch, DeliveryException } from "../../types";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import InboundExceptionActions from "./InboundExceptionActions";
import InboundAdjustmentActions from "./InboundAdjustmentActions";
import { useInboundAdjustments } from "./useInboundAdjustments";
import BatchManualAllowances from "./BatchManualAllowances";
import { allowanceKey } from "./inboundHandling";

const batch: Batch = {
  ...createDetailBatch(),
  workflow: "self_operated_inbound",
  manual_allowance_disabled_reason: null
};
const record = createDetailExceptions()[3];
const siteRecord = createDetailExceptions()[2];
afterEach(() => vi.unstubAllGlobals());

function Editor({
  rows = [record],
  currentBatch = batch,
  saved = vi.fn()
}: {
  rows?: DeliveryException[];
  currentBatch?: Batch;
  saved?: () => Promise<unknown>;
}) {
  const adjustments = useInboundAdjustments(currentBatch, saved);
  return (
    <>
      <InboundAdjustmentActions adjustments={adjustments} />
      {rows.map((row) => (
        <InboundExceptionActions
          key={row.id}
          record={row}
          supplierCode="GYS-023"
          adjustments={adjustments}
          onVersions={vi.fn()}
        />
      ))}
      <BatchManualAllowances
        batch={currentBatch}
        adjustments={adjustments}
        visibleKeys={new Set(rows.map((row) => allowanceKey("GYS-023", row)))}
      />
    </>
  );
}

describe("计算后行内调整草稿", () => {
  it("已无待办行的追加额度仍可填零，统一提交撤销", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(batch))
    );
    const currentBatch = {
      ...batch,
      manual_allowances: [
        {
          supplier_code: "GYS-023",
          supplier_name: "合成",
          sku: record.sku,
          full_site: record.full_site,
          quantity: 6,
          reason: ""
        }
      ]
    };
    const { rerender } = renderDetail(<Editor currentBatch={currentBatch} />);
    expect(screen.queryByText("已追加额度")).not.toBeInTheDocument();
    rerender(<Editor rows={[]} currentBatch={currentBatch} />);
    fireEvent.click(screen.getByText("已追加额度"));
    const input = screen.getByRole("spinbutton", { name: "本批追加" });
    expect(input).toHaveValue("6");
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "按调整重算（1 处）" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string).allowances[0].quantity).toBe(0);
  });
  it("追加默认为空，不再显示旧处理按钮，重复记录合并为一处", () => {
    renderDetail(<Editor rows={[record, { ...record, id: 100 }]} />);
    const inputs = screen.getAllByRole("spinbutton", { name: "本批追加" });
    expect(inputs[0]).toHaveValue("");
    for (const name of ["追加超收", "线下处理", "转交货", "查看并处理"])
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    fireEvent.change(inputs[0], { target: { value: "3" } });
    expect(inputs[1]).toHaveValue("3");
    expect(screen.getByRole("button", { name: "按调整重算（1 处）" })).toBeEnabled();
  });

  it("追加与站点只保存草稿，一次请求提交并阻止重复提交", async () => {
    const saved = vi.fn(async () => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(batch))
    );
    renderDetail(<Editor rows={[record, siteRecord]} saved={saved} />);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "4" } });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    expect(fetch).not.toHaveBeenCalled();
    const submit = screen.getByRole("button", { name: "按调整重算（2 处）" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledOnce();
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/batches/7/adjustments");
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toEqual({
      allowances: [{ supplier_code: "GYS-023", sku: record.sku, full_site: record.full_site, quantity: 4, reason: "" }],
      sites: [
        {
          file_id: siteRecord.batch_file_id,
          sku: siteRecord.sku,
          original_site: siteRecord.original_site,
          full_site: "AMAZON:OTHER:US"
        }
      ]
    });
    expect(screen.queryByRole("button", { name: /按调整重算/ })).not.toBeInTheDocument();
  });

  it("翻页或筛选后保留草稿，放弃修改统一清空", () => {
    const { rerender } = renderDetail(<Editor />);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "7" } });
    rerender(<Editor rows={[siteRecord]} />);
    expect(screen.getByRole("button", { name: "按调整重算（1 处）" })).toBeInTheDocument();
    rerender(<Editor />);
    expect(screen.getByRole("spinbutton")).toHaveValue("7");
    fireEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(screen.getByRole("spinbutton")).toHaveValue("");
    expect(screen.queryByRole("button", { name: /按调整重算/ })).not.toBeInTheDocument();
  });

  it("剩余为零仍能把已有追加改为零撤销", () => {
    renderDetail(
      <Editor
        rows={[{ ...record, offline_quantity: record.manual_quantity }]}
        currentBatch={{
          ...batch,
          manual_allowances: [
            {
              supplier_code: "GYS-023",
              supplier_name: "合成",
              sku: record.sku,
              full_site: record.full_site,
              quantity: 6,
              reason: ""
            }
          ]
        }}
      />
    );
    const input = screen.getByRole("spinbutton");
    expect(input).toHaveValue("6");
    expect(input).toBeEnabled();
    fireEvent.change(input, { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "按调整重算（1 处）" })).toBeEnabled();
  });

  it("失败保留草稿；有转交关联禁用调整并说明原因", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "输入已变化" }, 409))
    );
    const { rerender } = renderDetail(<Editor />);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /按调整重算/ }));
    expect(await screen.findByText("输入已变化")).toBeVisible();
    expect(screen.getByRole("spinbutton")).toHaveValue("2");
    rerender(<Editor currentBatch={{ ...batch, manual_allowance_disabled_reason: "批次已有转交记录" }} />);
    const input = screen.getByRole("spinbutton");
    expect(input).toBeDisabled();
    fireEvent.focus(input.closest(".ant-input-number")!.parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("批次已有转交记录");
  });

  it("未匹配仅显示资料链接，其他原因为空", () => {
    renderDetail(
      <Editor
        rows={[
          { ...record, reason: "产品信息未匹配" },
          { ...record, id: 99, reason: "其他" }
        ]}
      />
    );
    expect(screen.getByRole("button", { name: "查看锁定资料" })).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看并处理" })).not.toBeInTheDocument();
  });
});
