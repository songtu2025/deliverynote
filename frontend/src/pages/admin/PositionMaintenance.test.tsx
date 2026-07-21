import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { message } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { download } from "../../api";
import type { InputVersion } from "../../types";
import { PositionMaintenance } from "./PositionMaintenance";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, download: vi.fn() };
});

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const jsonResponse = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "Content-Type": "application/json" }
});

const version: InputVersion = {
  id: 31,
  kind: "position",
  name: "position-current",
  original_name: "position-current.xlsx",
  active: true,
  created_by: 1,
  created_at: "2026-07-21T09:00:00"
};

const baseDraft = {
  id: 7,
  kind: "position",
  base_version_id: 31,
  status: "editing",
  revision: 3,
  created_by: 1,
  updated_by: 2,
  created_at: "2026-07-21T09:10:00",
  updated_at: "2026-07-21T10:30:00",
  row_count: 1,
  modified_count: 0,
  diff: { added: 0, modified: 0, deleted: 0, unchanged: 1 },
  issues: [],
  error_count: 0,
  warning_count: 0,
  valid: true
};

const baseRow = {
  id: 101,
  draft_id: 7,
  row_order: 1,
  store_site: "SEEKWAY:US",
  jiaji_sku: "SKU-A",
  msku: "MSKU-A",
  scale_position: "短尾",
  stocking_position: "备货",
  ordered_days: "90",
  change_type: "unchanged",
  deleted: false,
  issues: []
};

let draftResponse = { ...baseDraft };
let rowsResponse: { rows: Array<Record<string, unknown>>; total: number; offset: number; limit: number };
let validationResponse: Record<string, unknown>;
let failEntry = false;
let entryRequest: Deferred<Response> | null = null;
let metadataRequest: Deferred<Response> | null = null;
let metadataResponse: Record<string, unknown> | null = null;
let conflictNextRowWrite = false;
let localConflictNextRowWrite = false;
let expireImportApply = false;
let duplicatePublishNameOnce = false;
let rowRequestHandler: ((url: string) => Promise<Response> | Response) | null = null;
let rowWriteRequest: Deferred<Response> | null = null;
let singleDeleteRequest: Deferred<Response> | null = null;
let bulkDeleteRequest: Deferred<Response> | null = null;
let discardRequest: Deferred<Response> | null = null;
let importApplyRequest: Deferred<Response> | null = null;
let publishRequest: Deferred<Response> | null = null;

function renderMaintenance(overrides: Partial<{
  onPublished: (published: InputVersion) => void;
  onBack: () => void;
}> = {}) {
  return render(
    <PositionMaintenance
      activeVersion={version}
      onPublished={overrides.onPublished ?? vi.fn()}
      onBack={overrides.onBack ?? vi.fn()}
    />
  );
}

function requests(method: string, suffix: string) {
  return vi.mocked(fetch).mock.calls.filter(([input, init]) =>
    String(input).includes(suffix) && (init?.method ?? "GET") === method
  );
}

async function dialogByTitle(title: string): Promise<HTMLElement> {
  const heading = await screen.findByText(title);
  const dialog = heading.closest('[role="dialog"]');
  expect(dialog).not.toBeNull();
  return dialog as HTMLElement;
}

describe("PositionMaintenance", () => {
  beforeEach(() => {
    draftResponse = { ...baseDraft };
    rowsResponse = { rows: [{ ...baseRow }], total: 1, offset: 0, limit: 20 };
    validationResponse = {
      draft_id: 7,
      revision: 3,
      diff: { added: 0, modified: 0, deleted: 0, unchanged: 1 },
      issues: [],
      error_count: 0,
      warning_count: 0,
      valid: true
    };
    failEntry = false;
    entryRequest = null;
    metadataRequest = null;
    metadataResponse = null;
    conflictNextRowWrite = false;
    localConflictNextRowWrite = false;
    expireImportApply = false;
    duplicatePublishNameOnce = false;
    rowRequestHandler = null;
    rowWriteRequest = null;
    singleDeleteRequest = null;
    bulkDeleteRequest = null;
    discardRequest = null;
    importApplyRequest = null;
    publishRequest = null;
    vi.mocked(download).mockReset();
    vi.spyOn(message, "success").mockImplementation(() => {
      const result = (() => undefined) as ReturnType<typeof message.success>;
      const completed = Promise.resolve(true);
      result.then = completed.then.bind(completed);
      return result;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/api/input-drafts/position") && method === "POST") {
        if (entryRequest) return entryRequest.promise;
        if (failEntry) return jsonResponse({ detail: "草稿服务暂时不可用" }, 500);
        return jsonResponse(draftResponse);
      }
      if (url.endsWith("/api/input-drafts/position") && method === "GET") {
        if (metadataRequest) return metadataRequest.promise;
        return jsonResponse(metadataResponse ?? draftResponse);
      }
      if (url.includes("/api/input-drafts/7/rows?") && method === "GET") {
        if (rowRequestHandler) return rowRequestHandler(url);
        return jsonResponse(rowsResponse);
      }
      if (url.endsWith("/api/input-drafts/7/rows") && method === "POST") {
        if (rowWriteRequest) return rowWriteRequest.promise;
        if (localConflictNextRowWrite) {
          localConflictNextRowWrite = false;
          return jsonResponse({ detail: "记录当前不可复制，请修正后重试" }, 409);
        }
        if (conflictNextRowWrite) {
          conflictNextRowWrite = false;
          return jsonResponse({ detail: "草稿已被其他管理员更新，请刷新后重试" }, 409);
        }
        return jsonResponse({ row: { ...baseRow, id: 102, change_type: "added" }, revision: 4 }, 201);
      }
      if (url.endsWith("/api/input-drafts/7/rows/101") && method === "PUT") {
        return jsonResponse({ row: { ...baseRow, stocking_position: "不备货", change_type: "modified" }, revision: 8 });
      }
      if (url.endsWith("/api/input-drafts/7/rows/101") && method === "DELETE") {
        if (singleDeleteRequest) return singleDeleteRequest.promise;
        return jsonResponse({ row_id: 101, revision: 9 });
      }
      if (url.endsWith("/api/input-drafts/7/rows/bulk-delete") && method === "POST") {
        if (bulkDeleteRequest) return bulkDeleteRequest.promise;
        return jsonResponse({ deleted_ids: [101], revision: 5 });
      }
      if (url.endsWith("/api/input-drafts/7/import-preview") && method === "POST") {
        return jsonResponse({
          token: "preview-token",
          draft_id: 7,
          revision: 3,
          row_count: 2,
          diff: { added: 2, modified: 1, deleted: 1, unchanged: 4 },
          issues: [{ severity: "warning", code: "row_count_changed", message: "数据量变化较大", row_numbers: [] }],
          error_count: 0,
          warning_count: 1,
          valid: true
        });
      }
      if (url.endsWith("/api/input-drafts/7/import-apply") && method === "POST") {
        if (importApplyRequest) return importApplyRequest.promise;
        if (expireImportApply) return jsonResponse({ detail: "导入预览已失效，请重新预览" }, 409);
        return jsonResponse({ diff: { added: 2, modified: 1, deleted: 1, unchanged: 4 }, revision: 6 });
      }
      if (url.endsWith("/api/input-drafts/7/validate") && method === "POST") {
        return jsonResponse(validationResponse);
      }
      if (url.endsWith("/api/input-drafts/7/publish") && method === "POST") {
        if (publishRequest) return publishRequest.promise;
        if (duplicatePublishNameOnce) {
          duplicatePublishNameOnce = false;
          return jsonResponse({ detail: "版本名称已存在" }, 409);
        }
        return jsonResponse({
          ...version,
          id: 32,
          name: "position-20260721",
          original_name: "position-20260721.xlsx",
          draft_revision: 4,
          draft_status: "published"
        }, 201);
      }
      if (url.endsWith("/api/input-drafts/7/discard") && method === "POST") {
        if (discardRequest) return discardRequest.promise;
        return jsonResponse({ ...draftResponse, status: "discarded", revision: 4 });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
    message.destroy();
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("resumes a server draft and saves a new row with the current revision", async () => {
    renderMaintenance();

    expect(await screen.findByText("草稿已自动保存")).toBeInTheDocument();
    expect(screen.getByText("已保存到服务器")).toBeInTheDocument();
    expect(screen.getByText("修订号 3")).toBeInTheDocument();
    expect(screen.getByText("新增 0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));

    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    const body = JSON.parse(String(requests("POST", "/api/input-drafts/7/rows")[0][1]?.body));
    expect(body).toMatchObject({ revision: 3, store_site: "SEEKWAY:UK", jiaji_sku: "SKU-B" });
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "新增库位记录" })).not.toBeInTheDocument();
  });

  it("edits with the current revision and uses only the returned revision for the next mutation", async () => {
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "编辑 SEEKWAY:US / SKU-A / MSKU-A" }));
    fireEvent.change(await screen.findByLabelText("备货定位"), { target: { value: "不备货" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
    expect(await screen.findByText("修订号 8")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));
    await waitFor(() => expect(requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    const copyBody = JSON.parse(String(requests("POST", "/api/input-drafts/7/rows")[0][1]?.body));
    expect(copyBody.revision).toBe(8);
  });

  it("merges refreshed metadata only when the summary matches the accepted r4", async () => {
    metadataResponse = {
      ...baseDraft,
      revision: 4,
      updated_by: 9,
      updated_at: "2026-07-21T11:00:00",
      modified_count: 1,
      diff: { added: 1, modified: 0, deleted: 0, unchanged: 1 }
    };
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));

    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
    expect(await screen.findByText("新增 1")).toBeInTheDocument();
    expect(screen.getByText("最后编辑人：用户 #9")).toBeInTheDocument();
  });

  it("treats an r5 metadata summary as a collaboration conflict without mixing it into local r4", async () => {
    metadataRequest = deferred<Response>();
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();

    metadataRequest.resolve(jsonResponse({
      ...baseDraft,
      revision: 5,
      updated_by: 12,
      updated_at: "2026-07-21T11:05:00",
      modified_count: 99,
      diff: { added: 99, modified: 0, deleted: 0, unchanged: 0 }
    }));

    expect(await screen.findByText("草稿已在其他位置更新")).toBeInTheDocument();
    expect(screen.getByText("修订号 4")).toBeInTheDocument();
    expect(screen.getByText("新增 0")).toBeInTheDocument();
    expect(screen.queryByText("新增 99")).not.toBeInTheDocument();
    expect(screen.queryByText("最后编辑人：用户 #12")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新增记录" })).toBeDisabled();
  });

  it("invalidates local editing after a 409 and offers a server refresh", async () => {
    conflictNextRowWrite = true;
    renderMaintenance();
    await screen.findByText("SKU-A");
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到草稿" }));

    expect(await screen.findByText("草稿已在其他位置更新")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "新增库位记录" })).not.toBeInTheDocument();
    draftResponse = { ...baseDraft, revision: 11, updated_at: "2026-07-21T11:00:00" };
    fireEvent.click(screen.getByRole("button", { name: "刷新草稿" }));
    expect(await screen.findByText("修订号 11")).toBeInTheDocument();
    expect(requests("POST", "/api/input-drafts/position")).toHaveLength(2);
  });

  it("keeps a non-revision row 409 local without locking the workspace", async () => {
    localConflictNextRowWrite = true;
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));

    expect(await screen.findByText("记录当前不可复制，请修正后重试")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" })).toBeEnabled();
  });

  it("keeps a single-row delete confirmation open while pending, then restores retry after failure", async () => {
    singleDeleteRequest = deferred<Response>();
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

    singleDeleteRequest.resolve(jsonResponse({ detail: "删除服务暂时不可用" }, 500));
    expect(await screen.findByText("删除服务暂时不可用")).toBeInTheDocument();
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeEnabled();

    singleDeleteRequest = deferred<Response>();
    fireEvent.click(screen.getByRole("button", { name: /确认删除/ }));
    await waitFor(() => expect(requests("DELETE", "/api/input-drafts/7/rows/101")).toHaveLength(2));
    singleDeleteRequest.resolve(jsonResponse({ row_id: 101, revision: 9 }));
    expect(await screen.findByText("修订号 9")).toBeInTheDocument();
    await waitFor(() => expect(deleteButton).not.toHaveClass("ant-popover-open"));
  });

  it("sends server filters and pagination, and a late response cannot replace newer rows", async () => {
    const slow = deferred<Response>();
    rowRequestHandler = (url) => {
      if (url.includes("search=old")) return slow.promise;
      if (url.includes("search=new")) {
        return jsonResponse({
          rows: [{ ...baseRow, id: 202, jiaji_sku: "LATEST-SKU" }],
          total: 45,
          offset: 0,
          limit: 20
        });
      }
      return jsonResponse({ ...rowsResponse, total: 45 });
    };
    renderMaintenance();
    await screen.findByText("SKU-A");

    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "old" } });
    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "new" } });
    expect(await screen.findByText("LATEST-SKU")).toBeInTheDocument();
    slow.resolve(jsonResponse({ rows: [{ ...baseRow, id: 201, jiaji_sku: "STALE-SKU" }], total: 1, offset: 0, limit: 20 }));
    await waitFor(() => expect(screen.queryByText("STALE-SKU")).not.toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("站点筛选"), { target: { value: "SEEKWAY:US" } });
    fireEvent.change(screen.getByLabelText("规模定位筛选"), { target: { value: "短尾" } });
    fireEvent.mouseDown(screen.getByLabelText("问题筛选"));
    fireEvent.click(await screen.findByText("仅错误"));
    fireEvent.click(screen.getByRole("checkbox", { name: "仅看已修改" }));
    fireEvent.click(await screen.findByTitle("2"));

    await waitFor(() => {
      const urls = requests("GET", "/api/input-drafts/7/rows?").map(([input]) => String(input));
      expect(urls.some((url) =>
        url.includes("search=new")
        && url.includes("site=SEEKWAY%3AUS")
        && url.includes("scale_position=%E7%9F%AD%E5%B0%BE")
        && url.includes("only_errors=true")
        && url.includes("only_modified=true")
        && url.includes("offset=20")
      )).toBe(true);
    });
  });

  it("keeps the bulk-delete confirmation open and uncancellable while pending", async () => {
    bulkDeleteRequest = deferred<Response>();
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

    bulkDeleteRequest.resolve(jsonResponse({ deleted_ids: [101], revision: 5 }));
    expect(await screen.findByText("修订号 5")).toBeInTheDocument();
    await waitFor(() => expect(bulkDeleteButton).not.toHaveClass("ant-popover-open"));
  });

  it("previews every Excel diff count before applying the server token", async () => {
    const { container } = renderMaintenance();
    await screen.findByText("SKU-A");
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: { files: [new File(["excel"], "replacement.xlsx", { type: "application/vnd.ms-excel" })] }
    });

    await waitFor(() => expect(requests("POST", "/import-preview")).toHaveLength(1));
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
  });

  it("recovers from an expired import token without applying the candidate", async () => {
    expireImportApply = true;
    const { container } = renderMaintenance();
    await screen.findByText("SKU-A");
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["excel"], "expired.xlsx")] }
    });
    await waitFor(() => expect(requests("POST", "/import-preview")).toHaveLength(1));
    const dialog = await dialogByTitle("Excel 整表替换预览");
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));

    expect(await screen.findByText("导入预览已失效，请重新预览")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();

    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["excel-2"], "retry.xlsx")] }
    });
    await waitFor(() => expect(requests("POST", "/import-preview")).toHaveLength(2));
  });

  it("blocks publish when validation returns errors", async () => {
    validationResponse = {
      ...validationResponse,
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
    validationResponse = {
      ...validationResponse,
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

  it("publishes a named version and reports success to the parent", async () => {
    const onPublished = vi.fn();
    renderMaintenance({ onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    expect(await screen.findByText("只影响之后批次，历史批次不变")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "position-20260721" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));

    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(onPublished.mock.calls[0][0]).toMatchObject({ id: 32, name: "position-20260721", active: true });
    const body = JSON.parse(String(requests("POST", "/publish")[0][1]?.body));
    expect(body).toEqual({ revision: 3, name: "position-20260721", confirm_warnings: false });
  });

  it("keeps a duplicate publish name editable and retries in the same dialog", async () => {
    duplicatePublishNameOnce = true;
    const onPublished = vi.fn();
    renderMaintenance({ onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    const dialog = await dialogByTitle("发布新的库位/排仓版本");
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "duplicate-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));

    expect(await within(dialog).findByText("版本名称已存在")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("新版本名称")).toHaveValue("duplicate-name");
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "unique-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布/ }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(requests("POST", "/publish")).toHaveLength(2);
  });

  it("downloads the draft and keeps discard confirmation uncancellable until the server accepts it", async () => {
    discardRequest = deferred<Response>();
    const onBack = vi.fn();
    renderMaintenance({ onBack });
    await screen.findByText("SKU-A");
    fireEvent.click(screen.getByRole("button", { name: "下载草稿" }));
    await waitFor(() => expect(download).toHaveBeenCalledWith(
      "/api/input-drafts/7/download",
      "position-draft-r3.xlsx"
    ));

    fireEvent.click(screen.getByRole("button", { name: "放弃草稿" }));
    expect(await screen.findByText("确定放弃整个服务器草稿？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认放弃" }));
    await waitFor(() => expect(requests("POST", "/discard")).toHaveLength(1));
    expect(screen.getByRole("button", { name: /取\s*消/ })).toBeDisabled();
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);
    expect(screen.getByText("确定放弃整个服务器草稿？")).toBeInTheDocument();
    expect(onBack).not.toHaveBeenCalled();

    discardRequest.resolve(jsonResponse({ ...draftResponse, status: "discarded", revision: 4 }));
    await waitFor(() => expect(onBack).toHaveBeenCalledOnce());
  });

  it("asks before returning only when the drawer contains unsaved form changes", async () => {
    const onBack = vi.fn();
    renderMaintenance({ onBack });
    await screen.findByText("SKU-A");

    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    expect(await screen.findByText("放弃未保存的表单修改？")).toBeInTheDocument();
    expect(onBack).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "放弃并返回" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("cannot leave or close the row drawer while a save request is pending", async () => {
    rowWriteRequest = deferred<Response>();
    const onBack = vi.fn();
    renderMaintenance({ onBack });
    await screen.findByText("SKU-A");
    fireEvent.click(screen.getByRole("button", { name: "新增记录" }));
    fireEvent.change(screen.getByLabelText("店铺-站点"), { target: { value: "SEEKWAY:UK" } });
    fireEvent.change(screen.getByLabelText("积加 SKU"), { target: { value: "SKU-B" } });
    const drawer = await dialogByTitle("新增库位记录");
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
    } finally {
      rowWriteRequest.resolve(jsonResponse({ row: { ...baseRow, id: 102 }, revision: 4 }, 201));
    }
    expect(await screen.findByText("修订号 4")).toBeInTheDocument();
  });

  it("cannot leave or cancel the import dialog while apply is pending", async () => {
    importApplyRequest = deferred<Response>();
    const { container } = renderMaintenance();
    await screen.findByText("SKU-A");
    fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
      target: { files: [new File(["excel"], "replacement.xlsx")] }
    });
    const dialog = await dialogByTitle("Excel 整表替换预览");
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
    await waitFor(() => expect(requests("POST", "/import-apply")).toHaveLength(1));

    try {
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: /取\s*消/ })).toBeDisabled();
      expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃草稿" })).toBeDisabled();
      fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
      expect(screen.getByText("Excel 整表替换预览")).toBeInTheDocument();
    } finally {
      importApplyRequest.resolve(jsonResponse({ diff: { added: 2, modified: 1, deleted: 1, unchanged: 4 }, revision: 6 }));
    }
    expect(await screen.findByText("修订号 6")).toBeInTheDocument();
  });

  it("cannot leave or cancel the publish dialog while publish is pending", async () => {
    publishRequest = deferred<Response>();
    const onBack = vi.fn();
    const onPublished = vi.fn();
    renderMaintenance({ onBack, onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    const dialog = await dialogByTitle("发布新的库位/排仓版本");
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "position-busy" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(requests("POST", "/publish")).toHaveLength(1));

    try {
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: "继续修改草稿" })).toBeDisabled();
      expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃草稿" })).toBeDisabled();
      fireEvent.click(within(dialog).getByRole("button", { name: "继续修改草稿" }));
      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      expect(onBack).not.toHaveBeenCalled();
      expect(screen.getByText("发布新的库位/排仓版本")).toBeInTheDocument();
    } finally {
      publishRequest.resolve(jsonResponse({
        ...version,
        id: 32,
        name: "position-busy",
        original_name: "position-busy.xlsx",
        draft_revision: 4,
        draft_status: "published"
      }, 201));
    }
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
  });

  it("can return to the input catalog while the draft entry request is loading", () => {
    entryRequest = deferred<Response>();
    const onBack = vi.fn();
    const view = renderMaintenance({ onBack });

    try {
      expect(screen.getByText("正在创建或恢复服务器草稿")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      expect(onBack).toHaveBeenCalledOnce();
    } finally {
      view.unmount();
      entryRequest.resolve(jsonResponse(draftResponse));
    }
  });

  it("can return to the input catalog after the draft entry request fails", async () => {
    failEntry = true;
    const onBack = vi.fn();
    renderMaintenance({ onBack });

    expect(await screen.findByText("无法打开库位草稿")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("shows loading, entry error with retry, and empty row states", async () => {
    entryRequest = deferred<Response>();
    const first = renderMaintenance();
    expect(screen.getByText("正在创建或恢复服务器草稿")).toBeInTheDocument();
    entryRequest.resolve(jsonResponse(draftResponse));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    first.unmount();

    entryRequest = null;
    failEntry = true;
    const failed = renderMaintenance();
    expect(await screen.findByText("无法打开库位草稿")).toBeInTheDocument();
    expect(screen.getByText("草稿服务暂时不可用")).toBeInTheDocument();
    failEntry = false;
    fireEvent.click(screen.getByRole("button", { name: /重新尝试/ }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    expect(requests("POST", "/api/input-drafts/position")).toHaveLength(3);
    failed.unmount();

    entryRequest = null;
    rowsResponse = { rows: [], total: 0, offset: 0, limit: 20 };
    renderMaintenance();
    expect(await screen.findByText("草稿中没有符合条件的记录")).toBeInTheDocument();
  });
});
