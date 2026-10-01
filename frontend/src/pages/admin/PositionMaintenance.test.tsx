import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp, message as staticMessage } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { download } from "../../api";
import type { InputVersion } from "../../types";
import { PositionMaintenance } from "./PositionMaintenance";
import {
  baseDraft,
  baseImportPreview,
  basePositionVersion as version,
  baseRow,
  deferred,
  jsonResponse
} from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, download: vi.fn() };
});

let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;

function renderMaintenance(
  overrides: Partial<{
    onPublished: (published: InputVersion) => void;
    onBack: () => void;
  }> = {}
) {
  return render(
    <AntApp>
      <PositionMaintenance
        activeVersion={version}
        onPublished={overrides.onPublished ?? vi.fn()}
        onBack={overrides.onBack ?? vi.fn()}
      />
    </AntApp>
  );
}

function requests(method: string, suffix: string) {
  return environment.fetch.mock.calls.filter(
    ([input, init]) => String(input).includes(suffix) && (init?.method ?? "GET") === method
  );
}

function fillNewRow() {
  fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
  fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
}

async function startRowSave() {
  renderMaintenance();
  await screen.findByText("SKU-A");
  fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
  fillNewRow();
  fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
}

async function dialogByTitle(title: string): Promise<HTMLElement> {
  const heading = await screen.findByText(title);
  const dialog = heading.closest('[role="dialog"]');
  expect(dialog).not.toBeNull();
  return dialog as HTMLElement;
}

function uploadImport(container: HTMLElement, name = "replacement.xlsx") {
  fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
    target: { files: [new File(["excel"], name)] }
  });
}

async function startImport(name = "replacement.xlsx") {
  const view = renderMaintenance();
  await screen.findByText("SKU-A");
  uploadImport(view.container, name);
  return { ...view, dialog: await dialogByTitle("Excel 整表替换预览") };
}

async function startPublish() {
  const onPublished = vi.fn();
  renderMaintenance({ onPublished });
  fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
  return { onPublished, dialog: await dialogByTitle("发布新的MSKU定位版本") };
}

describe("PositionMaintenance", () => {
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
    vi.mocked(download).mockReset();
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
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
    expect(await screen.findByText("请输入店铺-站点")).toBeInTheDocument();
    expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(0);
    fillNewRow();
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));

    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    const body = JSON.parse(String(requests("POST", "/api/input-drafts/7/rows")[0][1]?.body));
    expect(body).toMatchObject({ revision: 3, store_site: "SEEKWAY:UK", jiaji_sku: "SKU-B" });
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    await waitFor(() => expect(requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(2));
    expect(screen.queryByRole("dialog", { name: "新增库位记录" })).not.toBeInTheDocument();
    expect(await screen.findAllByText("记录已保存")).toHaveLength(1);
    expect(staticSuccess).not.toHaveBeenCalled();
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

  it("edits with the current revision and uses only the returned revision for the next mutation", async () => {
    renderMaintenance();
    const skuCell = await screen.findByText("SKU-A");
    const row = skuCell.closest("tr");
    expect(row).not.toBeNull();
    const rowControls = within(row!);

    fireEvent.click(rowControls.getByRole("button", { name: "编辑 SEEKWAY:US / SKU-A / MSKU-A" }));
    const editor = within(await dialogByTitle("编辑库位记录：SKU-A"));
    fireEvent.change(editor.getByLabelText("备货定位"), { target: { value: "不备货" } });
    fireEvent.click(editor.getByRole("button", { name: "保存到草稿" }));
    expect(await screen.findByText("修订号 8")).toBeInTheDocument();

    fireEvent.click(rowControls.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));
    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    const copyBody = JSON.parse(String(requests("POST", "/api/input-drafts/7/rows")[0][1]?.body));
    expect(copyBody.revision).toBe(8);
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
    expect(requests("POST", "/api/input-drafts/position")).toHaveLength(2);
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
    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(2));
    const nextBody = JSON.parse(String(requests("POST", "/api/input-drafts/7/rows")[1][1]?.body));
    expect(nextBody.revision).toBe(4);
  });

  it("ignores a late copy result after leaving the maintenance page", async () => {
    const response = deferred<Response>();
    environment.state.rowWriteRequest = response;
    const view = renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));
    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    view.unmount();
    await act(async () => {
      response.resolve(jsonResponse({ row: baseRow, revision: 4 }, 201));
    });
    expect(requests("GET", "/api/input-drafts/position")).toHaveLength(0);
    expect(requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(1);
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

    await waitFor(() => expect(requests("DELETE", "/api/input-drafts/7/rows/101")).toHaveLength(1));
    expect(JSON.parse(String(requests("DELETE", "/api/input-drafts/7/rows/101")[0][1]?.body))).toEqual({ revision: 3 });
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
    await waitFor(() => expect(requests("DELETE", "/api/input-drafts/7/rows/101")).toHaveLength(2));
    environment.state.singleDeleteRequest.resolve(jsonResponse({ row_id: 101, revision: 9 }));
    expect(await screen.findByText("修订号 9")).toBeInTheDocument();
    await waitFor(() => expect(deleteButton).not.toHaveClass("ant-popover-open"));
    expect(await screen.findAllByText("记录已从服务器草稿删除")).toHaveLength(1);
  }, 15_000);

  it("sends server filters and pagination, and a late response cannot replace newer rows", async () => {
    const slow = deferred<Response>();
    environment.state.rowRequestHandler = (url) => {
      if (url.includes("search=old")) return slow.promise;
      if (url.includes("search=new")) {
        return jsonResponse({
          rows: [{ ...baseRow, id: 202, jiaji_sku: "LATEST-SKU" }],
          total: 45,
          offset: 0,
          limit: 20
        });
      }
      return jsonResponse({ ...environment.state.rowsResponse, total: 45 });
    };
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(within(screen.getByText("SKU-A").closest("tr")!).getByRole("checkbox"));
    expect(screen.getByText("已选择 1 条")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "old" } });
    await waitFor(() => {
      expect(
        requests("GET", "/api/input-drafts/7/rows?").some(
          ([input]) => new URL(String(input), "http://test").searchParams.get("search") === "old"
        )
      ).toBe(true);
    });
    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "new" } });
    expect(await screen.findByText("LATEST-SKU")).toBeInTheDocument();
    expect(screen.getByText("已选择 0 条")).toBeInTheDocument();
    slow.resolve(
      jsonResponse({ rows: [{ ...baseRow, id: 201, jiaji_sku: "STALE-SKU" }], total: 1, offset: 0, limit: 20 })
    );
    await waitFor(() => expect(screen.queryByText("STALE-SKU")).not.toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("站点筛选"), { target: { value: "SEEKWAY:US" } });
    fireEvent.change(screen.getByLabelText("规模定位筛选"), { target: { value: "短尾" } });
    fireEvent.mouseDown(screen.getByLabelText("问题筛选"));
    fireEvent.click(await screen.findByText("仅错误"));
    fireEvent.click(screen.getByRole("checkbox", { name: "仅看已修改" }));
    fireEvent.click(await screen.findByTitle("2"));

    await waitFor(() => {
      const urls = requests("GET", "/api/input-drafts/7/rows?").map(([input]) => String(input));
      expect(
        urls.some(
          (url) =>
            url.includes("search=new") &&
            url.includes("site=SEEKWAY%3AUS") &&
            url.includes("scale_position=%E7%9F%AD%E5%B0%BE") &&
            url.includes("only_errors=true") &&
            url.includes("only_modified=true") &&
            url.includes("offset=20")
        )
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "重置筛选" }));
    await waitFor(() => {
      const calls = requests("GET", "/api/input-drafts/7/rows?");
      const params = new URL(String(calls.at(-1)![0]), "http://test").searchParams;
      expect(Object.fromEntries(params)).toEqual({ offset: "0", limit: "20" });
    });
    expect(screen.getByLabelText("搜索草稿")).toHaveValue("");
    expect(screen.getByLabelText("站点筛选")).toHaveValue("");
    expect(screen.getByLabelText("规模定位筛选")).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: "仅看已修改" })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "重置筛选" })).not.toBeInTheDocument();
  });

  it("retries a failed row read without reopening the draft", async () => {
    environment.state.rowRequestHandler = () => jsonResponse({ detail: "草稿记录暂时不可用" }, 500);
    renderMaintenance();
    expect(await screen.findByText("草稿记录暂时不可用")).toBeInTheDocument();
    expect(screen.queryByText("SKU-A")).not.toBeInTheDocument();

    environment.state.rowRequestHandler = () => jsonResponse(environment.state.rowsResponse);
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    expect(screen.queryByText("无法读取草稿记录")).not.toBeInTheDocument();
    expect(requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(2);
    expect(requests("POST", "/api/input-drafts/position")).toHaveLength(1);
  });

  it("debounces rapid text filters before requesting rows", async () => {
    renderMaintenance();
    await screen.findByText("SKU-A");

    const search = screen.getByLabelText("搜索草稿");
    fireEvent.change(search, { target: { value: "s" } });
    fireEvent.change(search, { target: { value: "sk" } });
    fireEvent.change(search, { target: { value: "sku" } });

    await waitFor(() => {
      const values = requests("GET", "/api/input-drafts/7/rows?")
        .map(([input]) => new URL(String(input), "http://test").searchParams.get("search"))
        .filter(Boolean);
      expect(values).toEqual(["sku"]);
    });
  });

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

    await waitFor(() => expect(requests("POST", "/rows/bulk-delete")).toHaveLength(1));
    expect(JSON.parse(String(requests("POST", "/rows/bulk-delete")[0][1]?.body))).toEqual({
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
    await waitFor(() => expect(requests("GET", "/api/input-drafts/7/rows?")).toHaveLength(2));
    await waitFor(() => expect(bulkDeleteButton).not.toHaveClass("ant-popover-open"));
  });

  it("previews every Excel diff count before applying the server token", async () => {
    const { container } = renderMaintenance();
    await screen.findByText("SKU-A");
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    uploadImport(container);

    await waitFor(() => expect(requests("POST", "/import-preview")).toHaveLength(1));
    const previewBody = requests("POST", "/import-preview")[0][1]?.body as FormData;
    expect(previewBody.get("revision")).toBe("3");
    expect((previewBody.get("file") as File).name).toBe("replacement.xlsx");
    expect(requests("POST", "/import-apply")).toHaveLength(0);
    expect(screen.queryByText("Excel 替换未完成")).not.toBeInTheDocument();
    const previewDialog = await dialogByTitle("Excel 整表替换预览");
    expect(within(previewDialog).getByText("新增 2")).toBeInTheDocument();
    expect(within(previewDialog).getByText("修改 1")).toBeInTheDocument();
    expect(within(previewDialog).getByText("删除 1")).toBeInTheDocument();
    expect(within(previewDialog).getByText("未变化 4")).toBeInTheDocument();
    expect(within(previewDialog).getByText("数据量变化较大")).toBeInTheDocument();
    fireEvent.click(within(previewDialog).getByRole("button", { name: "应用整表替换" }));

    await waitFor(() => expect(requests("POST", "/import-apply")).toHaveLength(1));
    expect(JSON.parse(String(requests("POST", "/import-apply")[0][1]?.body))).toEqual({
      revision: 3,
      token: "preview-token"
    });
    expect(await screen.findByText("修订号 6")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^复制 / }));
    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    expect(JSON.parse(String(requests("POST", "/api/input-drafts/7/rows")[0][1]?.body)).revision).toBe(6);
  });

  it("recovers from an expired import token without applying the candidate", async () => {
    environment.state.expireImportApply = true;
    const { container, dialog } = await startImport("expired.xlsx");
    await waitFor(() => expect(requests("POST", "/import-preview")).toHaveLength(1));
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));

    expect(await screen.findByText("请重新上传表格预览")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();

    uploadImport(container, "retry.xlsx");
    await waitFor(() => expect(requests("POST", "/import-preview")).toHaveLength(2));
  });

  it("cancels import without writing and opens only the next file preview", async () => {
    const { container, dialog } = await startImport("cancelled.xlsx");
    fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Excel 整表替换" })).toHaveFocus());
    expect(requests("POST", "/import-apply")).toHaveLength(0);
    uploadImport(container, "next.xlsx");
    expect(await screen.findByText("即将用 next.xlsx 的 2 行完整替换当前草稿")).toBeInTheDocument();
    expect(screen.queryByText(/即将用 cancelled.xlsx/)).not.toBeInTheDocument();
    expect(screen.getByText("修订号 3")).toBeInTheDocument();
  });

  it("keeps failed apply local and requires reupload if its token was consumed", async () => {
    let failed = false;
    environment.state.importRequestHandler = (stage) => {
      if (stage === "preview") return jsonResponse(baseImportPreview);
      if (!failed) {
        failed = true;
        return jsonResponse({ detail: "替换暂时失败" }, 500);
      }
      return jsonResponse({ detail: "令牌已消费，请重新预览", code: "draft_import_preview_expired" }, 409);
    };
    const { dialog } = await startImport();
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
    expect(await screen.findByText("替换暂时失败")).toBeInTheDocument();
    expect(screen.getByText("修订号 3")).toBeInTheDocument();
    expect(screen.queryByText("Excel 已完整替换服务器草稿")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    const retry = within(dialog).getByRole("button", { name: /应用整表替换/ });
    await waitFor(() => expect(retry).not.toHaveClass("ant-btn-loading"));
    fireEvent.click(retry);
    expect(await screen.findByText("令牌已消费，请重新预览")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument());
    expect(requests("POST", "/import-apply")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();
  });

  it.each(["preview", "apply"] as const)(
    "locks the workspace for %s revision conflict and refreshes it",
    async (stage) => {
      environment.state.importRequestHandler = (currentStage) =>
        currentStage === stage
          ? jsonResponse({ detail: "导入修订号冲突", code: "draft_revision_conflict" }, 409)
          : jsonResponse(baseImportPreview);
      const { container } = renderMaintenance();
      await screen.findByText("SKU-A");
      uploadImport(container);
      if (stage === "apply") {
        const dialog = await dialogByTitle("Excel 整表替换预览");
        fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
      }
      expect(await screen.findByText("导入修订号冲突")).toBeInTheDocument();
      expect(screen.queryByText("Excel 替换未完成")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeDisabled();
      expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument();
      environment.state.draftResponse = { ...baseDraft, revision: 9 };
      fireEvent.click(screen.getByRole("button", { name: "刷新草稿" }));
      expect(await screen.findByText("修订号 9")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();
    }
  );

  it("blocks publish when validation returns errors", async () => {
    environment.state.validationResponse = {
      ...environment.state.validationResponse,
      valid: false,
      error_count: 1,
      issues: [{ severity: "error", code: "empty_site", message: "店铺-站点不能为空", row_numbers: [2] }]
    };
    renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));

    expect(await screen.findByText("存在 1 个错误，修正后才能发布")).toBeInTheDocument();
    expect(screen.getByText("店铺-站点不能为空")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
  });

  it("requires explicit warning confirmation before publish", async () => {
    environment.state.validationResponse = {
      ...environment.state.validationResponse,
      warning_count: 1,
      issues: [{ severity: "warning", code: "custom_scale", message: "规模定位不是常用值", row_numbers: [2] }]
    };
    renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));

    expect(await screen.findByText("存在 1 个警告，请确认后发布")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "我已检查并确认发布这些警告" }));
    expect(screen.getByRole("button", { name: "确认发布" })).toBeEnabled();
  });

  it("keeps publish actions reachable when validation lists many issues", async () => {
    environment.state.validationResponse = {
      ...environment.state.validationResponse,
      warning_count: 4,
      issues: [
        { severity: "warning", code: "custom_scale", message: "规模定位必须为短尾、中尾或长尾", row_numbers: [3] },
        { severity: "warning", code: "empty_stocking", message: "备货定位不能为空", row_numbers: [3] },
        { severity: "warning", code: "row_count_changed", message: "行数变化达到或超过 50%", row_numbers: [] }
      ]
    };
    renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));

    const dialog = await dialogByTitle("发布新的MSKU定位版本");
    const body = dialog.querySelector<HTMLElement>(".ant-modal-body");
    expect(body).toHaveStyle({
      maxHeight: "calc(100vh - 300px)",
      overflowY: "auto"
    });
    const footer = dialog.querySelector<HTMLElement>(".ant-modal-footer");
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: "继续修改草稿" }));
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: "确认发布" }));
    expect(body).not.toContainElement(within(dialog).getByRole("button", { name: "确认发布" }));
  });

  it("publishes a named version and reports success to the parent", async () => {
    const onPublished = vi.fn<(published: InputVersion) => void>(() => {
      view.rerender(
        <AntApp>
          <h2>基础资料目录</h2>
        </AntApp>
      );
    });
    const view = renderMaintenance({ onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    expect(await screen.findByText("仅用于新批次；已有批次不变")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "position-20260721" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));

    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(onPublished.mock.calls[0][0]).toMatchObject({ id: 32, name: "position-20260721", active: true });
    expect(screen.queryByText("MSKU 定位维护")).not.toBeInTheDocument();
    expect(await screen.findAllByText("新库位版本已发布并启用")).toHaveLength(1);
    const body = JSON.parse(String(requests("POST", "/publish")[0][1]?.body));
    expect(body).toEqual({ revision: 3, name: "position-20260721", confirm_warnings: false });
  });

  it("keeps a duplicate publish name editable and retries in the same dialog", async () => {
    environment.state.duplicatePublishNameOnce = true;
    const { onPublished, dialog } = await startPublish();
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "duplicate-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));

    expect(await within(dialog).findByText("请更换版本名称")).toBeInTheDocument();
    expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("新版本名称")).toHaveValue("duplicate-name");
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "unique-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布/ }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(requests("POST", "/publish")).toHaveLength(2);
    expect(await screen.findAllByText("新库位版本已发布并启用")).toHaveLength(1);
  });

  it("refreshes metadata after a publish base-version conflict and still allows discarding", async () => {
    environment.state.publishRequestHandler = (stage) => {
      if (stage === "validate") return jsonResponse(environment.state.validationResponse);
      environment.state.draftResponse = { ...baseDraft, active_version_id: 42, active_version_name: "position-newer" };
      return jsonResponse(
        { detail: "当前启用的库位版本已变化，请放弃当前草稿后重新开始", code: "draft_base_version_changed" },
        409
      );
    };
    const { onPublished, dialog } = await startPublish();
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    await screen.findByText("草稿基线已过期");
    expect(screen.getByRole("button", { name: "放弃草稿" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /发布新版本$/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(onPublished).not.toHaveBeenCalled();
    await waitFor(() => expect(dialog).toHaveClass("ant-zoom-leave-active"));
    // jsdom 没有 AnimationEvent，动画库监听的是带前缀的结束事件。
    fireEvent(dialog, new Event("webkitAnimationEnd", { bubbles: true }));
    await waitFor(() => expect(dialog).not.toBeVisible());
  }, 30_000);

  it.each([500, 409])("preserves publish input on an ordinary failure %i and retries", async (status) => {
    let failed = false;
    environment.state.publishRequestHandler = (stage) => {
      if (stage === "validate") return jsonResponse(environment.state.validationResponse);
      if (!failed) {
        failed = true;
        return jsonResponse({ detail: "发布服务暂时不可用" }, status);
      }
      return jsonResponse({ ...version, id: 32, draft_revision: 4, draft_status: "published" }, 201);
    };
    const { onPublished, dialog } = await startPublish();
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "keep-publish-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    expect(await within(dialog).findByText("发布服务暂时不可用")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("新版本名称")).toHaveValue("keep-publish-name");
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(onPublished).not.toHaveBeenCalled();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: /确认发布$/ })).toBeEnabled());
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布$/ }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(requests("POST", "/publish")).toHaveLength(2);
  });

  it("clears warning confirmation on cancellation and restores the publish button focus", async () => {
    environment.state.validationResponse = { ...environment.state.validationResponse, warning_count: 1 };
    renderMaintenance();
    const trigger = await screen.findByRole("button", { name: "发布新版本" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await dialogByTitle("发布新的MSKU定位版本");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "我已检查并确认发布这些警告" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "继续修改草稿" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(requests("POST", "/publish")).toHaveLength(0);
    fireEvent.click(trigger);
    const reopened = await dialogByTitle("发布新的MSKU定位版本");
    expect(within(reopened).getByRole("checkbox", { name: "我已检查并确认发布这些警告" })).not.toBeChecked();
    expect(within(reopened).getByRole("button", { name: "确认发布" })).toBeDisabled();
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
    await waitFor(() => expect(requests("POST", "/discard")).toHaveLength(1));
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

  it.each([500, 409])(
    "keeps failed form input and retries without advancing revision after %s",
    async (status) => {
      environment.state.rowWriteRequest = deferred<Response>();
      await startRowSave();
      await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
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
      const writes = requests("POST", "/api/input-drafts/7/rows");
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
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    const drawer = await dialogByTitle("新增库位记录");
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));

    try {
      await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(drawer).getByRole("button", { name: /取\s*消/ })).toBeDisabled();
      expect(within(drawer).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      fireEvent.click(within(drawer).getByRole("button", { name: /取\s*消/ }));
      expect(onBack).not.toHaveBeenCalled();
      expect(screen.getByText("新增库位记录")).toBeInTheDocument();
      expect(screen.queryByText("记录已保存")).not.toBeInTheDocument();
    } finally {
      environment.state.rowWriteRequest.resolve(jsonResponse({ row: { ...baseRow, id: 102 }, revision: 4 }, 201));
    }
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    expect(await screen.findAllByText("记录已保存")).toHaveLength(1);
  });

  it("cannot leave or cancel the import dialog while apply is pending", async () => {
    environment.state.importApplyRequest = deferred<Response>();
    const { dialog } = await startImport();
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /应用整表替换/ }));
    await waitFor(() => expect(requests("POST", "/import-apply")).toHaveLength(1));

    try {
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: /取\s*消/ })).toBeDisabled();
      expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃草稿" })).toBeDisabled();
      fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
      expect(screen.getByText("Excel 整表替换预览")).toBeInTheDocument();
      expect(screen.queryByText("Excel 已完整替换服务器草稿")).not.toBeInTheDocument();
    } finally {
      environment.state.importApplyRequest.resolve(jsonResponse({ diff: baseImportPreview.diff, revision: 6 }));
    }
    expect(await screen.findByText("修订号 6")).toBeInTheDocument();
    expect(await screen.findAllByText("Excel 已完整替换服务器草稿")).toHaveLength(1);
  });

  it("cannot leave or cancel the publish dialog while publish is pending", async () => {
    environment.state.publishRequest = deferred<Response>();
    const onBack = vi.fn();
    const onPublished = vi.fn();
    renderMaintenance({ onBack, onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    const dialog = await dialogByTitle("发布新的MSKU定位版本");
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "position-busy" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布/ }));
    await waitFor(() => expect(requests("POST", "/publish")).toHaveLength(1));

    try {
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: "继续修改草稿" })).toBeDisabled();
      expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃草稿" })).toBeDisabled();
      expect(within(dialog).getByLabelText("新版本名称")).toBeDisabled();
      fireEvent.click(within(dialog).getByRole("button", { name: "继续修改草稿" }));
      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      expect(onBack).not.toHaveBeenCalled();
      expect(screen.getByText("发布新的MSKU定位版本")).toBeInTheDocument();
      expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
    } finally {
      environment.state.publishRequest.resolve(
        jsonResponse(
          {
            ...version,
            id: 32,
            name: "position-busy",
            original_name: "position-busy.xlsx",
            draft_revision: 4,
            draft_status: "published"
          },
          201
        )
      );
    }
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(await screen.findAllByText("新库位版本已发布并启用")).toHaveLength(1);
  }, 30_000);

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
    expect(requests("POST", "/api/input-drafts/position")).toHaveLength(3);
    failed.unmount();

    environment.state.entryRequest = null;
    environment.state.rowsResponse = { rows: [], total: 0, offset: 0, limit: 20 };
    renderMaintenance();
    expect(await screen.findByText("草稿中没有符合条件的记录")).toBeInTheDocument();
  });
});
