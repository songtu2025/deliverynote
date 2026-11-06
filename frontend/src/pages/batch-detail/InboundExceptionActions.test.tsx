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
  saved = vi.fn(),
  opened = vi.fn()
}: {
  rows?: DeliveryException[];
  currentBatch?: Batch;
  saved?: () => Promise<unknown>;
  opened?: (row: DeliveryException) => void;
}) {
  const adjustments = useInboundAdjustments(currentBatch, saved);
  return (
    <>
      <InboundAdjustmentActions adjustments={adjustments} />
      {rows.flatMap((row) =>
        (["site", "actions"] as const).map((placement) => (
          <InboundExceptionActions
            key={`${row.id}:${placement}`}
            placement={placement}
            record={row}
            onOpen={opened}
            adjustments={adjustments}
            onVersions={vi.fn()}
          />
        ))
      )}
      <BatchManualAllowances batch={currentBatch} onSaved={saved} />
    </>
  );
}

describe("计算后行内调整", () => {
  it("超收行只显示指定超收，点击打开对应详情", () => {
    const opened = vi.fn();
    renderDetail(<Editor rows={[record, { ...record, id: 100, reason: "超出应收货" }]} opened={opened} />);
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /按调整重算/ })).not.toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "指定超收" });
    fireEvent.click(buttons[0]);
    expect(opened).toHaveBeenCalledWith(record);
    fireEvent.click(buttons[1]);
    expect(opened).toHaveBeenLastCalledWith(expect.objectContaining({ id: 100 }));
  });

  it("站点仍只保存草稿，一次请求提交并阻止重复提交", async () => {
    const saved = vi.fn(async () => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(batch))
    );
    renderDetail(<Editor rows={[record, siteRecord]} saved={saved} />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    expect(fetch).not.toHaveBeenCalled();
    const submit = screen.getByRole("button", { name: "按调整重算（1 处）" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledOnce();
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toEqual({
      allowances: [],
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

  it("站点草稿翻页保留，放弃修改清空", () => {
    const { rerender } = renderDetail(<Editor rows={[siteRecord]} />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    rerender(<Editor />);
    expect(screen.getByRole("button", { name: /按调整重算/ })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(screen.queryByRole("button", { name: /按调整重算/ })).not.toBeInTheDocument();
  });

  it("无待办的旧格式额度仍能通过统一接口撤销", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(batch))
    );
    renderDetail(
      <Editor
        rows={[]}
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
    fireEvent.click(screen.getByText("已追加额度"));
    fireEvent.click(screen.getByRole("button", { name: "撤销追加" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string).allowances[0].quantity).toBe(0);
  });

  it("失败保留站点草稿；转交后禁用重算但仍可查看详情", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "输入已变化" }, 409))
    );
    const { rerender } = renderDetail(<Editor rows={[siteRecord]} />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    fireEvent.click(screen.getByRole("button", { name: /按调整重算/ }));
    expect(await screen.findByText("输入已变化")).toBeVisible();
    rerender(<Editor currentBatch={{ ...batch, manual_allowance_disabled_reason: "批次已有转交记录" }} />);
    expect(screen.getByRole("button", { name: /按调整重算/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "指定超收" })).toBeEnabled();
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
  });
  it("切换批次清空原批次的调整草稿", () => {
    const { rerender } = renderDetail(<Editor rows={[siteRecord]} />);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "选择站点" }));
    fireEvent.click(screen.getAllByText("AMAZON:OTHER:US").at(-1)!);
    expect(screen.getByRole("button", { name: /按调整重算/ })).toBeEnabled();
    rerender(<Editor rows={[siteRecord]} currentBatch={{ ...batch, id: 8 }} />);
    expect(screen.queryByRole("button", { name: /按调整重算/ })).not.toBeInTheDocument();
  });
});
