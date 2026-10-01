import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, AUTH_EXPIRED_EVENT, api } from "../../api";
import * as positionDraftApi from "./positionDraftApi";

const rowValues = {
  store_site: "SEEKWAY:US",
  jiaji_sku: "演示 SKU",
  msku: "演示 MSKU",
  scale_position: "自定义定位",
  stocking_position: "备货"
};
const revision = 8;
const publishPayload = { revision, name: "演示版本", confirm_warnings: true };

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

describe("position draft API contracts", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ revision: 9 }))
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each([
    { call: () => positionDraftApi.createOrResumeDraft(), path: "/position", method: "POST" },
    { call: () => positionDraftApi.getDraft(), path: "/position", method: "GET" },
    { call: () => positionDraftApi.validateDraft(7), path: "/7/validate", method: "POST" },
    {
      call: () => positionDraftApi.createRow(7, { revision, ...rowValues }),
      path: "/7/rows",
      method: "POST",
      body: { revision, ...rowValues }
    },
    {
      call: () => positionDraftApi.updateRow(7, 101, { revision, ...rowValues }),
      path: "/7/rows/101",
      method: "PUT",
      body: { revision, ...rowValues }
    },
    {
      call: () => positionDraftApi.deleteRow(7, 101, revision),
      path: "/7/rows/101",
      method: "DELETE",
      body: { revision }
    },
    {
      call: () => positionDraftApi.deleteRows(7, revision, [101, 102]),
      path: "/7/rows/bulk-delete",
      method: "POST",
      body: { revision, row_ids: [101, 102] }
    },
    {
      call: () => positionDraftApi.applyImport(7, revision, "演示预览 token"),
      path: "/7/import-apply",
      method: "POST",
      body: { revision, token: "演示预览 token" }
    },
    {
      call: () => positionDraftApi.publishDraft(7, publishPayload),
      path: "/7/publish",
      method: "POST",
      body: publishPayload
    },
    {
      call: () => positionDraftApi.discardDraft(7, revision),
      path: "/7/discard",
      method: "POST",
      body: { revision }
    }
  ])("preserves $method $path and its body", async ({ call, path, method, body }) => {
    await call();

    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`/api/input-drafts${path}`);
    expect(init?.method ?? "GET").toBe(method);
    expect(init?.credentials).toBe("include");
    const headers = new Headers(init?.headers);
    expect(headers.has("Authorization")).toBe(false);
    if (body) {
      expect(JSON.parse(String(init?.body))).toEqual(body);
      expect(headers.get("Content-Type")).toBe("application/json");
    } else {
      expect(init?.body).toBeUndefined();
      expect(headers.has("Content-Type")).toBe(false);
    }
  });

  it("encodes trimmed filters without losing special characters or pagination", async () => {
    await positionDraftApi.listRows(7, {
      offset: 40,
      limit: 20,
      search: "  演示 SKU & +/?  ",
      site: " SEEKWAY:US ",
      scale_position: " 自定义定位 ",
      only_errors: true,
      only_modified: true
    });

    const [input, init] = vi.mocked(fetch).mock.calls[0];
    const url = new URL(String(input), "http://localhost");
    expect(url.pathname).toBe("/api/input-drafts/7/rows");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      offset: "40",
      limit: "20",
      search: "演示 SKU & +/?",
      site: "SEEKWAY:US",
      scale_position: "自定义定位",
      only_errors: "true",
      only_modified: "true"
    });
    expect(init?.credentials).toBe("include");
  });

  it("omits empty and disabled filters", async () => {
    await positionDraftApi.listRows(7, {
      offset: 0,
      limit: 100,
      search: " ",
      site: "",
      scale_position: " ",
      only_errors: false,
      only_modified: false
    });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/input-drafts/7/rows?offset=0&limit=100");
  });

  it("uploads the file and revision as FormData without a JSON content type", async () => {
    const file = new File(["合成测试数据"], "演示数据.xlsx");
    await positionDraftApi.previewImport(7, revision, file);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/input-drafts/7/import-preview");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.body).toBeInstanceOf(FormData);
    const form = init?.body as FormData;
    expect(form.get("revision")).toBe("8");
    expect(form.get("file")).toBe(file);
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  });

  it("returns the authoritative row and revision unchanged", async () => {
    const payload = {
      row: { ...rowValues, id: 101, draft_id: 7, row_order: 1, change_type: "modified", deleted: false, issues: [] },
      revision: 9
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(payload));
    expect(await positionDraftApi.updateRow(7, 101, { revision, ...rowValues })).toEqual(payload);
  });

  it.each([
    { call: () => positionDraftApi.createRow(7, { revision, ...rowValues }), code: "draft_revision_conflict" },
    { call: () => positionDraftApi.applyImport(7, revision, "expired"), code: "draft_import_preview_expired" },
    { call: () => positionDraftApi.publishDraft(7, publishPayload), code: "input_version_name_exists" },
    { call: () => positionDraftApi.publishDraft(7, publishPayload), code: "draft_base_version_changed" },
    { call: () => positionDraftApi.createRow(7, { revision, ...rowValues }), code: null }
  ])("retains the 409 error code $code", async ({ call, code }) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "演示失败信息", code }, 409));
    const result = call();
    await expect(result).rejects.toBeInstanceOf(ApiError);
    await expect(result).rejects.toMatchObject({ status: 409, message: "演示失败信息", code });
  });

  it.each([403, 422, 500])("retains status %i without converting failure to success", async (status) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "演示失败信息" }, status));
    await expect(positionDraftApi.getDraft()).rejects.toMatchObject({ status, message: "演示失败信息", code: null });
  });

  it.each([
    { status: 409, code: "draft_revision_conflict", conflict: true },
    { status: 409, code: "draft_import_preview_expired", conflict: false },
    { status: 409, code: "input_version_name_exists", conflict: false },
    { status: 409, code: "draft_base_version_changed", conflict: false },
    { status: 409, code: null, conflict: false },
    { status: 500, code: "draft_revision_conflict", conflict: false },
    { status: 500, code: "draft_base_version_changed", conflict: false }
  ])(
    "classifies status $status and code $code without treating every 409 as a revision conflict",
    ({ status, code, conflict }) => {
      const failure = new ApiError(status, "演示失败信息", code);
      expect(positionDraftApi.isRevisionConflict(failure)).toBe(conflict);
      expect(positionDraftApi.hasApiCode(failure, positionDraftApi.POSITION_ERROR_CODES.baseVersionChanged)).toBe(
        status === 409 && code === "draft_base_version_changed"
      );
      expect(positionDraftApi.hasApiCode(failure, positionDraftApi.POSITION_ERROR_CODES.importPreviewExpired)).toBe(
        status === 409 && code === "draft_import_preview_expired"
      );
    }
  );

  it("lets the shared request layer handle an expired session", async () => {
    await api("/api/auth/me");
    const onExpired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    try {
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "未登录" }, 401));
      await expect(positionDraftApi.getDraft()).rejects.toMatchObject({ status: 401 });
      expect(onExpired).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
    }
  });

  it("preserves network failures", async () => {
    const failure = new TypeError("演示网络故障");
    vi.mocked(fetch).mockRejectedValueOnce(failure);
    await expect(positionDraftApi.getDraft()).rejects.toBe(failure);
  });

  it("downloads with the existing filename and releases the blob URL", async () => {
    const createObjectURL = vi.fn(() => "blob:position-draft");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("position-draft-r8.xlsx");
      expect(this.getAttribute("href")).toBe("blob:position-draft");
    });
    vi.mocked(fetch).mockResolvedValueOnce(new Response("合成下载内容"));

    await positionDraftApi.downloadDraft(7, revision);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/input-drafts/7/download");
    expect(init?.credentials).toBe("include");
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:position-draft");
    expect(document.querySelector('a[download="position-draft-r8.xlsx"]')).toBeNull();
  });

  it("does not create a download URL when the server rejects the download", async () => {
    const createObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL });
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "禁止下载" }, 403));
    await expect(positionDraftApi.downloadDraft(7, revision)).rejects.toMatchObject({
      status: 403,
      message: "下载失败"
    });
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
