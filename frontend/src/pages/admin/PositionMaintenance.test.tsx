import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { download } from "../../api";
import { baseDraft, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";
import { dialogByTitle, renderMaintenance, startRowSave } from "./positionMaintenancePageTestSupport";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, download: vi.fn() };
});

let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;

describe("PositionMaintenance", () => {
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
    vi.mocked(download).mockReset();
  });

  afterEach(() => {
    environment.dispose();
  });

  it("presents the position draft as a labelled desktop workbench", async () => {
    renderMaintenance();

    expect(await screen.findByRole("table", { name: "库位草稿记录" })).toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "草稿摘要" });
    expect(within(summary).getByText("草稿记录")).toBeInTheDocument();
    expect(within(summary).getByText("已变更")).toBeInTheDocument();
    expect(within(summary).getByText("相对正式版")).toBeInTheDocument();
    expect(screen.getByText("搜索", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("站点", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("规模定位", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("问题", { selector: "label" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重置筛选" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "SKU-A" } });
    expect(screen.getByRole("button", { name: "重置筛选" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    const drawer = await dialogByTitle("新增库位记录");
    expect(within(drawer).getByText("MSKU（可选）")).toBeInTheDocument();
    expect(within(drawer).getByText("规模定位（可选）")).toBeInTheDocument();
    expect(within(drawer).queryByText(/optional/i)).not.toBeInTheDocument();
  });

  it("shows authoritative draft totals instead of deriving them from the current page", async () => {
    environment.state.draftResponse = {
      ...baseDraft,
      row_count: 6000,
      modified_count: 320,
      error_count: 3,
      warning_count: 5,
      valid: false,
      diff: { added: 10, modified: 310, deleted: 20, unchanged: 5680 }
    };
    renderMaintenance();
    await screen.findByText("SKU-A");

    const summary = within(screen.getByRole("region", { name: "草稿摘要" }));
    for (const value of ["6000", "320", "3", "5"]) {
      expect(summary.getByText(value, { exact: true })).toBeInTheDocument();
    }
    expect(summary.getByText("发布前必须修正")).toBeInTheDocument();
    expect(summary.getByText("发布前需要确认")).toBeInTheDocument();
    expect(summary.getByText("新增 10")).toBeInTheDocument();
    expect(summary.getByText("修改 310")).toBeInTheDocument();
    expect(summary.getByText("删除 20")).toBeInTheDocument();
    expect(summary.getByText("未变化 5680")).toBeInTheDocument();
  });

  it("shows the real draft base and blocks edits when the active version changed", async () => {
    environment.state.draftResponse = {
      ...baseDraft,
      base_version_id: 30,
      base_version_name: "position-v1",
      active_version_id: 31,
      active_version_name: "position-current"
    };
    renderMaintenance();

    expect(await screen.findByText(/基于 position-v1/)).toBeInTheDocument();
    expect(screen.getByText("草稿基线已过期")).toBeInTheDocument();
    expect(screen.getByText(/正式版本已变为 position-current/)).toBeInTheDocument();
    expect(screen.getByLabelText("新增记录")).toBeDisabled();
    expect(screen.getByLabelText("Excel 整表替换")).toBeDisabled();
    expect(screen.getByText("发布新版本").closest("button")).toBeDisabled();
    expect(screen.getByText("放弃草稿").closest("button")).toBeEnabled();
  });

  it("uses authoritative draft metadata when the catalog prop is stale", async () => {
    environment.state.draftResponse = {
      ...baseDraft,
      base_version_id: 32,
      base_version_name: "position-v2",
      active_version_id: 32,
      active_version_name: "position-v2"
    };
    renderMaintenance();

    expect(await screen.findByText(/基于 position-v2/)).toBeInTheDocument();
    expect(screen.queryByText("草稿基线已过期")).not.toBeInTheDocument();
    expect(screen.getByLabelText("新增记录")).toBeEnabled();
    expect(screen.getByLabelText("Excel 整表替换")).toBeEnabled();
    expect(screen.getByText("发布新版本").closest("button")).toBeEnabled();
  });

  it("merges refreshed metadata only when the summary matches the accepted r4", async () => {
    environment.state.metadataResponse = {
      ...baseDraft,
      revision: 4,
      updated_by: 9,
      updated_at: "2026-07-21T11:00:00",
      modified_count: 1,
      diff: { added: 1, modified: 0, deleted: 0, unchanged: 1 }
    };
    await startRowSave();

    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    expect(await screen.findByText("新增 1")).toBeInTheDocument();
    expect(screen.getByText("最后编辑人：用户 #9")).toBeInTheDocument();
  });

  it("treats an r5 metadata summary as a collaboration conflict without mixing it into local r4", async () => {
    environment.state.metadataRequest = deferred<Response>();
    await startRowSave();
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();

    environment.state.metadataRequest.resolve(
      jsonResponse({
        ...baseDraft,
        revision: 5,
        updated_by: 12,
        updated_at: "2026-07-21T11:05:00",
        modified_count: 99,
        diff: { added: 99, modified: 0, deleted: 0, unchanged: 0 }
      })
    );

    expect(await screen.findByText("草稿已在其他位置更新")).toBeInTheDocument();
    expect(screen.getByText("修订号 4")).toBeInTheDocument();
    expect(screen.getByText("新增 0")).toBeInTheDocument();
    expect(screen.queryByText("新增 99")).not.toBeInTheDocument();
    expect(screen.queryByText("最后编辑人：用户 #12")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新增记录" })).toBeDisabled();
  });

  it("invalidates local editing after a 409 and offers a server refresh", async () => {
    environment.state.conflictNextRowWrite = true;
    await startRowSave();

    expect(await screen.findByText("草稿已在其他位置更新")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "新增库位记录" })).not.toBeInTheDocument();
    environment.state.draftResponse = { ...baseDraft, revision: 11, updated_at: "2026-07-21T11:00:00" };
    fireEvent.click(screen.getByRole("button", { name: "刷新草稿" }));
    expect(await screen.findByText("修订号 11")).toBeInTheDocument();
    expect(environment.requests("POST", "/api/input-drafts/position")).toHaveLength(2);
  });

  it("downloads the draft and keeps discard confirmation uncancellable until the server accepts it", async () => {
    environment.state.discardRequest = deferred<Response>();
    const onBack = vi.fn();
    renderMaintenance({ onBack });
    await screen.findByText("SKU-A");
    fireEvent.click(screen.getByRole("button", { name: "下载草稿" }));
    await waitFor(() =>
      expect(download).toHaveBeenCalledWith("/api/input-drafts/7/download", "position-draft-r3.xlsx")
    );

    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(await screen.findByText("确定放弃整个服务器草稿？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认放弃" }));
    await waitFor(() => expect(environment.requests("POST", "/discard")).toHaveLength(1));
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeDisabled();
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);
    expect(screen.getByText("确定放弃整个服务器草稿？")).toBeInTheDocument();
    expect(onBack).not.toHaveBeenCalled();

    expect(screen.queryByText("服务器草稿已放弃，当前正式版本未改变")).not.toBeInTheDocument();

    environment.state.discardRequest.resolve(
      jsonResponse({ ...environment.state.draftResponse, status: "discarded", revision: 4 })
    );
    await waitFor(() => expect(onBack).toHaveBeenCalledOnce());
    expect(await screen.findAllByText("服务器草稿已放弃，当前正式版本未改变")).toHaveLength(1);
  });

  it("can return to the input catalog while the draft entry request is loading", () => {
    environment.state.entryRequest = deferred<Response>();
    const onBack = vi.fn();
    const view = renderMaintenance({ onBack });

    try {
      expect(screen.getByText("正在创建或恢复服务器草稿")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      expect(onBack).toHaveBeenCalledOnce();
    } finally {
      view.unmount();
      environment.state.entryRequest.resolve(jsonResponse(environment.state.draftResponse));
    }
  });

  it("can return to the input catalog after the draft entry request fails", async () => {
    environment.state.failEntry = true;
    const onBack = vi.fn();
    renderMaintenance({ onBack });

    expect(await screen.findByText("无法打开库位草稿")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("shows loading, entry error with retry, and empty row states", async () => {
    environment.state.entryRequest = deferred<Response>();
    const first = renderMaintenance();
    expect(screen.getByText("正在创建或恢复服务器草稿")).toBeInTheDocument();
    environment.state.entryRequest.resolve(jsonResponse(environment.state.draftResponse));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    first.unmount();

    environment.state.entryRequest = null;
    environment.state.failEntry = true;
    const failed = renderMaintenance();
    expect(await screen.findByText("无法打开库位草稿")).toBeInTheDocument();
    expect(screen.getByText("草稿服务暂时不可用")).toBeInTheDocument();
    environment.state.failEntry = false;
    fireEvent.click(screen.getByRole("button", { name: /重新尝试/ }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    expect(environment.requests("POST", "/api/input-drafts/position")).toHaveLength(3);
    failed.unmount();

    environment.state.entryRequest = null;
    environment.state.rowsResponse = { rows: [], total: 0, offset: 0, limit: 20 };
    renderMaintenance();
    expect(await screen.findByText("草稿中没有符合条件的记录")).toBeInTheDocument();
  });
});
