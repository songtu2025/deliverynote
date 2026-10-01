import { act, fireEvent, isInaccessible, screen, waitFor, within } from "@testing-library/react";
import { message as staticMessage } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { baseRow, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";
import { dialogByTitle, fillNewRow, renderMaintenance, startRowSave } from "./positionMaintenancePageTestSupport";

let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;

describe("PositionMaintenance record mutations", () => {
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
  });

  afterEach(() => {
    environment.dispose();
  });

  it("resumes a server draft and saves a new row with the current revision", async () => {
    const staticSuccess = vi.spyOn(staticMessage, "success");
    renderMaintenance();

    expect(await screen.findByText("草稿已自动保存")).toBeInTheDocument();
    expect(screen.getByText("修订号 3")).toBeInTheDocument();
    expect(screen.getByText("新增 0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    const drawer = await dialogByTitle("新增库位记录");
    expect(drawer.querySelector(".position-row-drawer-header")).toBeInTheDocument();
    expect(drawer.querySelector(".position-row-drawer-body")).toBeInTheDocument();
    expect(drawer.querySelector(".position-row-drawer-footer")).toBeInTheDocument();
    expect(drawer.querySelectorAll(".position-row-field")).toHaveLength(5);
    expect(drawer.querySelectorAll(".position-row-field-help")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
    expect(await screen.findByText("请输入店铺-站点")).toBeInTheDocument();
    expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(0);
    fillNewRow();
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));

    await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    const body = JSON.parse(String(environment.requests("POST", "/api/input-drafts/7/rows")[0][1]?.body));
    expect(body).toMatchObject({ revision: 3, store_site: "SEEKWAY:UK", jiaji_sku: "SKU-B" });
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    await waitFor(() => expect(environment.requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(2));
    expect(screen.queryByRole("dialog", { name: "新增库位记录" })).not.toBeInTheDocument();
    expect(await screen.findAllByText("记录已保存")).toHaveLength(1);
    expect(staticSuccess).not.toHaveBeenCalled();
  });

  it("edits with the current revision and uses only the returned revision for the next mutation", async () => {
    renderMaintenance();
    const skuCell = await screen.findByText("SKU-A");
    const row = skuCell.closest("tr");
    expect(row).not.toBeNull();
    const rowControls = within(row!);
    // 按明确标签定位单个按钮，保留原角色查询的名称与可访问性检查。
    const editButton = rowControls.getByLabelText("编辑 SEEKWAY:US / SKU-A / MSKU-A", { selector: "button" });
    const copyButton = rowControls.getByLabelText("复制 SEEKWAY:US / SKU-A / MSKU-A", { selector: "button" });
    expect(editButton).toHaveRole("button");
    expect(editButton).toHaveAccessibleName("编辑 SEEKWAY:US / SKU-A / MSKU-A");
    expect(isInaccessible(editButton)).toBe(false);

    fireEvent.click(editButton);
    const editor = within(await dialogByTitle("编辑库位记录：SKU-A"));
    fireEvent.change(editor.getByLabelText("备货定位"), { target: { value: "不备货" } });
    fireEvent.click(editor.getByRole("button", { name: "保存到草稿" }));
    expect(await screen.findByText("修订号 8")).toBeInTheDocument();

    expect(copyButton).toBeInTheDocument();
    expect(copyButton).toBeEnabled();
    expect(copyButton).toHaveRole("button");
    expect(copyButton).toHaveAccessibleName("复制 SEEKWAY:US / SKU-A / MSKU-A");
    expect(isInaccessible(copyButton)).toBe(false);
    fireEvent.click(copyButton);
    await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    const copyBody = JSON.parse(String(environment.requests("POST", "/api/input-drafts/7/rows")[0][1]?.body));
    expect(copyBody.revision).toBe(8);
  });

  it("keeps a successful write usable when the following metadata refresh fails", async () => {
    environment.state.metadataRequest = deferred<Response>();
    renderMaintenance();
    await screen.findByText("SKU-A");
    const copyButton = screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" });
    fireEvent.click(copyButton);
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    environment.state.metadataRequest.resolve(jsonResponse({ detail: "演示摘要刷新失败" }, 500));
    expect(await screen.findAllByText("记录已复制到服务器草稿")).toHaveLength(1);
    await waitFor(() => expect(copyButton).toBeEnabled());
    expect(screen.queryByText("草稿已在其他位置更新")).not.toBeInTheDocument();
    expect(screen.queryByText("演示摘要刷新失败")).not.toBeInTheDocument();

    fireEvent.click(copyButton);
    await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(2));
    const nextBody = JSON.parse(String(environment.requests("POST", "/api/input-drafts/7/rows")[1][1]?.body));
    expect(nextBody.revision).toBe(4);
  });

  it("ignores a late copy result after leaving the maintenance page", async () => {
    const response = deferred<Response>();
    environment.state.rowWriteRequest = response;
    const view = renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));
    await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    view.unmount();
    await act(async () => {
      response.resolve(jsonResponse({ row: baseRow, revision: 4 }, 201));
    });
    expect(environment.requests("GET", "/api/input-drafts/position")).toHaveLength(0);
    expect(environment.requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(1);
    expect(screen.queryByText("记录已复制到服务器草稿")).not.toBeInTheDocument();
  });

  it("keeps a non-revision row 409 local without locking the workspace", async () => {
    environment.state.localConflictNextRowWrite = true;
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));

    expect(await screen.findByText("记录当前不可复制，请修正后重试")).toBeInTheDocument();
    expect(screen.queryByText("记录已复制到服务器草稿")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" })).toBeEnabled();
  }, 15_000);

  it("keeps a single-row delete confirmation open while pending, then restores retry after failure", async () => {
    environment.state.singleDeleteRequest = deferred<Response>();
    renderMaintenance();
    await screen.findByText("SKU-A");

    const deleteButton = screen.getByRole("button", { name: "删除 SEEKWAY:US / SKU-A / MSKU-A" });
    fireEvent.click(deleteButton);
    const title = "删除 SKU-A？";
    expect(await screen.findByText(title)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(environment.requests("DELETE", "/api/input-drafts/7/rows/101")).toHaveLength(1));
    expect(JSON.parse(String(environment.requests("DELETE", "/api/input-drafts/7/rows/101")[0][1]?.body))).toEqual({
      revision: 3
    });
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeDisabled();
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);
    expect(screen.getByText(title)).toBeInTheDocument();

    environment.state.singleDeleteRequest.resolve(jsonResponse({ detail: "删除服务暂时不可用" }, 500));
    expect(await screen.findByText("删除服务暂时不可用")).toBeInTheDocument();
    expect(screen.queryByText("记录已从服务器草稿删除")).not.toBeInTheDocument();
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeEnabled();

    environment.state.singleDeleteRequest = deferred<Response>();
    fireEvent.click(screen.getByRole("button", { name: /确认删除/ }));
    await waitFor(() => expect(environment.requests("DELETE", "/api/input-drafts/7/rows/101")).toHaveLength(2));
    environment.state.singleDeleteRequest.resolve(jsonResponse({ row_id: 101, revision: 9 }));
    expect(await screen.findByText("修订号 9")).toBeInTheDocument();
    await waitFor(() => expect(deleteButton).not.toHaveClass("ant-popover-open"));
    expect(await screen.findAllByText("记录已从服务器草稿删除")).toHaveLength(1);
  }, 15_000);

  it("keeps the bulk-delete confirmation open and uncancellable while pending", async () => {
    environment.state.bulkDeleteRequest = deferred<Response>();
    renderMaintenance();
    await screen.findByText("SKU-A");
    const row = screen.getByText("SKU-A").closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row!).getByRole("checkbox"));
    const bulkDeleteButton = screen.getByRole("button", { name: "批量删除（1）" });
    fireEvent.click(bulkDeleteButton);
    expect(await screen.findByText("删除选中的 1 条记录？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(environment.requests("POST", "/rows/bulk-delete")).toHaveLength(1));
    expect(JSON.parse(String(environment.requests("POST", "/rows/bulk-delete")[0][1]?.body))).toEqual({
      revision: 3,
      row_ids: [101]
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /取\s*消/ })).toBeDisabled());
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);
    expect(screen.getByText("删除选中的 1 条记录？")).toBeInTheDocument();

    environment.state.bulkDeleteRequest.resolve(jsonResponse({ deleted_ids: [101], revision: 5 }));
    expect(await screen.findByText("修订号 5")).toBeInTheDocument();
    expect(screen.getByText("已选择 0 条")).toBeInTheDocument();
    await waitFor(() => expect(environment.requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(2));
    await waitFor(() => expect(bulkDeleteButton).not.toHaveClass("ant-popover-open"));
  });

  it.each([500, 409])(
    "keeps failed form input and retries without advancing revision after %s",
    async (status) => {
      environment.state.rowWriteRequest = deferred<Response>();
      await startRowSave();
      await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
      environment.state.rowWriteRequest.resolve(jsonResponse({ detail: "演示记录保存失败，请重试" }, status));
      expect(await screen.findByText("演示记录保存失败，请重试")).toBeInTheDocument();
      expect(screen.getByLabelText("店铺-站点")).toHaveValue("SEEKWAY:UK");
      expect(screen.getByLabelText("积加 SKU")).toHaveValue("SKU-B");
      expect(screen.getByText("修订号 3")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
      environment.state.rowWriteRequest = null;
      await waitFor(() => expect(screen.getByRole("button", { name: "返回基础资料" })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /保存到草稿$/ }));
      expect(await screen.findByText("修订号 4")).toBeInTheDocument();
      const writes = environment.requests("POST", "/api/input-drafts/7/rows");
      expect(writes).toHaveLength(2);
      expect(writes.map(([, init]) => JSON.parse(String(init?.body)).revision)).toEqual([3, 3]);
      expect(screen.queryByRole("dialog", { name: "新增库位记录" })).not.toBeInTheDocument();
    },
    15_000
  );

  it("asks before returning only when the drawer contains unsaved form changes", async () => {
    const onBack = vi.fn();
    renderMaintenance({ onBack });
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    expect(await screen.findByText("放弃未保存的表单修改？")).toBeInTheDocument();
    expect(onBack).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("店铺-站点")).toHaveValue("SEEKWAY:UK");
    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    expect(await screen.findByText("放弃未保存的表单修改？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放弃并返回" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("cannot leave or close the row drawer while a save request is pending", async () => {
    environment.state.rowWriteRequest = deferred<Response>();
    const onBack = vi.fn();
    renderMaintenance({ onBack });
    await screen.findByText("SKU-A");
    const backButton = screen.getByRole("button", { name: "返回基础资料" });
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    const drawer = await dialogByTitle("新增库位记录");
    const saveButton = within(drawer).getByRole("button", { name: "保存到草稿" });
    const cancelButton = within(drawer).getByRole("button", { name: /取\s*消/ });
    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    try {
      await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
      expect(backButton).toBeDisabled();
      expect(cancelButton).toBeDisabled();
      expect(within(drawer).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      fireEvent.click(backButton);
      fireEvent.click(cancelButton);
      expect(onBack).not.toHaveBeenCalled();
      expect(screen.getByText("新增库位记录")).toBeInTheDocument();
      expect(screen.queryByText("记录已保存")).not.toBeInTheDocument();
    } finally {
      environment.state.rowWriteRequest.resolve(jsonResponse({ row: { ...baseRow, id: 102 }, revision: 4 }, 201));
    }
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    expect(await screen.findAllByText("记录已保存")).toHaveLength(1);
  });
});
