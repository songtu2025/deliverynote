import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ManualHandling from "./ManualHandling";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import ExceptionTransfers from "./ExceptionTransfers";
import BatchManualAllowances from "./BatchManualAllowances";

const batch = { ...createDetailBatch(), status: "succeeded", manual_allowance_disabled_reason: null };
const exception = {
  ...createDetailExceptions()[0],
  manual_quantity: 8,
  transferred_quantity: 2,
  offline_quantity: 1,
  offline_note: "原备注"
};

describe("人工处理", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(exception))));
  const show = (overrides = {}, record = exception, onSaved = vi.fn()) =>
    renderDetail(
      <ManualHandling batch={{ ...batch, ...overrides }} exception={record} supplierCode="GYS-023" onSaved={onSaved} />
    );

  it("展示算式与默认值，复用扣除线下处理的剩余量", () => {
    show();
    expect(remainingTransferQuantity(exception)).toBe(5);
    expect(screen.getByText("待处理 8 = 已转交货 2 + 线下处理 1 + 剩余 5")).toBeVisible();
    const allowance = within(screen.getByRole("region", { name: "本批追加超收" }));
    expect(allowance.getByRole("spinbutton")).toHaveValue("5");
    const offline = within(screen.getByRole("region", { name: "线下处理" }));
    expect(offline.getByRole("spinbutton")).toHaveValue("1");
    expect(offline.getByLabelText("备注")).toHaveValue("原备注");
  });

  it("原因必填，追加先确认再调用并刷新", async () => {
    const saved = vi.fn();
    show({}, exception, saved);
    fireEvent.click(screen.getByRole("button", { name: "追加并重算" }));
    expect(await screen.findByText("请填写原因")).toBeVisible();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("原因"), { target: { value: "补录" } });
    fireEvent.click(screen.getByRole("button", { name: "追加并重算" }));
    await waitFor(() => expect(screen.getByText("将重新计算整批，现有结果需重新生成。")).toBeVisible());
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "重算整批" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith());
    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toContain('"quantity":5');
  });

  it("线下处理拒绝超量，保存与撤销无需重算", async () => {
    const saved = vi.fn();
    show({}, exception, saved);
    const region = within(screen.getByRole("region", { name: "线下处理" }));
    fireEvent.change(region.getByRole("spinbutton"), { target: { value: "9" } });
    fireEvent.click(region.getByRole("button", { name: "修改线下处理" }));
    expect(await region.findByText("请输入 1 至 6 的整数")).toBeVisible();
    fireEvent.change(region.getByRole("spinbutton"), { target: { value: "4" } });
    fireEvent.click(region.getByRole("button", { name: "修改线下处理" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith(exception));
    fireEvent.click(region.getByRole("button", { name: "撤销线下处理" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetch).mock.calls[1][1]?.body).toContain('"quantity":0');
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("显示后端禁用原因，已有追加值和撤销入口", () => {
    show({
      manual_allowance_disabled_reason: "批次已有转交记录，请先处理超收再转交",
      manual_allowances: [
        {
          supplier_code: "GYS-023",
          sku: exception.sku,
          full_site: exception.full_site,
          quantity: 7,
          reason: "既有原因"
        }
      ]
    });
    expect(screen.getByRole("button", { name: "追加并重算" })).toBeDisabled();
    expect(screen.getByText("批次已有转交记录，请先处理超收再转交")).toBeVisible();
    expect(screen.getByLabelText("原因")).toHaveValue("既有原因");
    expect(screen.getByRole("button", { name: "撤销本批追加超收" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "修改线下处理" })).toBeEnabled();
  });

  it("列表依据显示线下处理数量", () => {
    renderDetail(<ExceptionTransfers record={exception} />);
    expect(screen.getByText("线下处理 1 件")).toBeVisible();
  });

  it("待处理行消失后仍可从批次额度撤销，沿用后端可重算状态", async () => {
    const saved = vi.fn();
    renderDetail(
      <BatchManualAllowances
        batch={{
          ...batch,
          status: "failed",
          manual_allowances: [
            {
              supplier_code: "GYS-023",
              supplier_name: "合成供应商",
              sku: "SKU-A",
              full_site: exception.full_site,
              quantity: 7,
              reason: "确认实收"
            }
          ]
        }}
        onSaved={saved}
      />
    );
    fireEvent.click(screen.getByText(/合成供应商.*本批追加 7 件/));
    fireEvent.click(await screen.findByRole("button", { name: "撤销本批追加超收" }));
    fireEvent.click(await screen.findByRole("button", { name: "重算整批" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toContain('"quantity":0');
  });
});
