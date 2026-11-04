import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Batch } from "../../types";
import { renderDetail } from "../batchDetailTestSupport";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions, fixtureJob } from "./detailFixtures";
import InboundExceptionActions from "./InboundExceptionActions";
import { useExceptionTransfer } from "./useExceptionTransfer";

const batch: Batch = {
  ...createDetailBatch(),
  workflow: "self_operated_inbound",
  status: "succeeded",
  manual_allowance_disabled_reason: null
};
const record = { ...createDetailExceptions()[3], manual_quantity: 8, transferred_quantity: 2, offline_quantity: 1 };
afterEach(() => vi.unstubAllGlobals());

function show(overrides: Partial<Batch> = {}, remaining = record, onSaved = vi.fn(async () => undefined)) {
  const onTransfer = vi.fn();
  const onOpen = vi.fn();
  renderDetail(
    <InboundExceptionActions
      batch={{ ...batch, ...overrides }}
      record={remaining}
      supplierCode="GYS-023"
      onOpen={onOpen}
      onTransfer={onTransfer}
      onSaved={onSaved}
    />
  );
  return { onTransfer, onOpen, onSaved };
}

describe("计算后行内处理", () => {
  it("超量显示三种操作，其他原因不显示追加，查看仍打开原详情", () => {
    const { onOpen, onTransfer } = show();
    fireEvent.click(screen.getByRole("button", { name: "查看并处理" }));
    expect(onOpen).toHaveBeenCalledWith(record);
    fireEvent.click(screen.getByRole("button", { name: "转交货" }));
    expect(onTransfer).toHaveBeenCalledWith(record);
    expect(screen.getByRole("button", { name: "追加超收" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "线下处理" })).toBeEnabled();
  });
  it.each(["产品信息未匹配", "其他"])("%s 仅线下处理和转交", (reason) => {
    show({}, { ...record, reason });
    expect(screen.queryByRole("button", { name: "追加超收" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "线下处理" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "转交货" })).toBeEnabled();
  });
  it("后端追加禁用原因和导出期间禁用沿用现有逻辑", async () => {
    show({ manual_allowance_disabled_reason: "批次已有转交记录", jobs: { export: fixtureJob({ kind: "export" }) } });
    for (const name of ["追加超收", "线下处理", "转交货"]) expect(screen.getByRole("button", { name })).toBeDisabled();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "追加超收" }).parentElement!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("批次已有转交记录");
  });
  it("全部转交与线下处理后只保留详情", () => {
    show({}, { ...record, transferred_quantity: 5, offline_quantity: 3 });
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "查看并处理" })).toBeEnabled();
  });
  it("Modal 复用追加表单及确认，提交后刷新并关闭", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({}))
    );
    const { onSaved } = show();
    fireEvent.click(screen.getByRole("button", { name: "追加超收" }));
    const modal = within(await screen.findByRole("dialog"));
    expect(modal.getByRole("spinbutton")).toHaveValue("5");
    fireEvent.change(modal.getByLabelText("原因"), { target: { value: "确认实收" } });
    fireEvent.click(modal.getByRole("button", { name: "追加并重算" }));
    fireEvent.click(await screen.findByRole("button", { name: "重算整批" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith(
      "/api/batches/7/manual-allowances",
      expect.objectContaining({ body: expect.stringContaining('"quantity":5') })
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
  it("Modal 复用线下处理表单，成功后刷新", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(record))
    );
    const { onSaved } = show();
    fireEvent.click(screen.getByRole("button", { name: "线下处理" }));
    const modal = within(await screen.findByRole("dialog"));
    fireEvent.change(modal.getByLabelText("备注"), { target: { value: "线下入库" } });
    fireEvent.click(modal.getByRole("button", { name: "修改线下处理" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith(
      `/api/exceptions/${record.id}/offline-handling`,
      expect.objectContaining({ method: "PUT" })
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
  it("单行转交直接使用原 hook 的弹窗并仅选中当前行", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ sites: [record.full_site], purchases: [], queried_at: "2026-11-04", purchase_error: null })
      )
    );
    function Row() {
      const transfer = useExceptionTransfer(batch, vi.fn());
      return (
        <>
          {transfer.action}
          <InboundExceptionActions
            batch={batch}
            record={record}
            supplierCode="GYS-023"
            onOpen={vi.fn()}
            onTransfer={(row) => transfer.openRow?.(row)}
            onSaved={vi.fn()}
          />
          {transfer.modal}
        </>
      );
    }
    renderDetail(<Row />);
    fireEvent.click(screen.getByRole("button", { name: "转交货" }));
    expect(screen.getByText("已选 1 条")).toBeInTheDocument();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: `${record.sku} 转交数量` })).toHaveValue("5");
  });
});
