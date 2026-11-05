import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ManualHandling from "./ManualHandling";
import { createDetailBatch, createDetailExceptions } from "./detailFixtures";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import BatchManualAllowances from "./BatchManualAllowances";

const batch = {
  ...createDetailBatch(),
  workflow: "self_operated_inbound" as const,
  manual_allowance_disabled_reason: null
};
const exception = {
  ...createDetailExceptions()[3],
  manual_quantity: 8,
  transferred_quantity: 2,
  offline_quantity: 1,
  offline_note: "原备注"
};
const allowance = {
  supplier_code: "GYS-023",
  supplier_name: "合成供应商",
  sku: exception.sku,
  full_site: exception.full_site,
  quantity: 7,
  reason: "既有原因"
};

function show(overrides = {}, onSaved = vi.fn(async () => undefined)) {
  renderDetail(
    <ManualHandling batch={{ ...batch, ...overrides }} exception={exception} supplierCode="GYS-023" onSaved={onSaved} />
  );
}
function chooseAllowance() {
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "处理方式" }));
  fireEvent.click(screen.getAllByText("追加超收").at(-1)!);
}

describe("紧凑人工处理表单", () => {
  beforeEach(() =>
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(exception))
    )
  );
  it("只显示一个表单，默认展示已有线下处理及可选备注", () => {
    show();
    expect(screen.getByText("待处理 8 = 已转交货 2 + 线下处理 1 + 剩余 5")).toBeVisible();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
    expect(screen.getByRole("spinbutton")).toHaveValue("1");
    expect(screen.getByLabelText("备注（选填）")).toHaveValue("原备注");
  });
  it("切换为追加后，原因可空，直接保存并刷新", async () => {
    const saved = vi.fn(async () => undefined);
    show({}, saved);
    chooseAllowance();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
    expect(screen.getByRole("spinbutton")).toHaveValue("5");
    fireEvent.click(screen.getByRole("button", { name: "保存并重算" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]?.body as string)).toMatchObject({ quantity: 5, reason: "" });
  });
  it("线下拒绝超量，修改与撤销不弹窗", async () => {
    const saved = vi.fn(async () => undefined);
    show({}, saved);
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "保存线下处理" }));
    expect(await screen.findByText("请输入 1 至 6 的整数")).toBeVisible();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("备注（选填）"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "保存线下处理" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith(exception));
    fireEvent.click(screen.getByRole("button", { name: "撤销线下处理" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetch).mock.calls[1][1]?.body).toContain('"quantity":0');
  });
  it("已有追加默认显示，保留后端禁用原因", () => {
    show({ manual_allowances: [allowance], manual_allowance_disabled_reason: "批次已有转交记录" });
    expect(screen.getByLabelText("原因（选填）")).toHaveValue("既有原因");
    expect(screen.getByRole("button", { name: "保存并重算" })).toBeDisabled();
    expect(screen.getByText("批次已有转交记录")).toBeVisible();
  });
  it("待处理行消失后可从批次额度修改或撤销", async () => {
    const saved = vi.fn(async () => undefined);
    renderDetail(<BatchManualAllowances batch={{ ...batch, manual_allowances: [allowance] }} onSaved={saved} />);
    fireEvent.click(screen.getByText(/合成供应商.*本批追加 7 件/));
    fireEvent.click(await screen.findByRole("button", { name: "撤销本批追加超收" }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toContain('"quantity":0');
  });
});
