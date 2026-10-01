import { vi } from "vitest";

import type { PositionDraft, PositionDraftRowsPage, PositionDraftValidation } from "../../types";
import {
  baseDraft,
  baseImportPreview,
  basePositionVersion,
  baseRow,
  baseValidation,
  jsonResponse
} from "./positionDraftTestSupport";
import type { Deferred } from "./positionDraftTestSupport";

interface PositionMaintenanceTestState {
  draftResponse: PositionDraft;
  rowsResponse: PositionDraftRowsPage;
  validationResponse: PositionDraftValidation;
  failEntry: boolean;
  entryRequest: Deferred<Response> | null;
  metadataRequest: Deferred<Response> | null;
  metadataResponse: PositionDraft | null;
  conflictNextRowWrite: boolean;
  localConflictNextRowWrite: boolean;
  expireImportApply: boolean;
  duplicatePublishNameOnce: boolean;
  rowRequestHandler: ((url: string) => Promise<Response> | Response) | null;
  rowWriteRequest: Deferred<Response> | null;
  singleDeleteRequest: Deferred<Response> | null;
  bulkDeleteRequest: Deferred<Response> | null;
  discardRequest: Deferred<Response> | null;
  importApplyRequest: Deferred<Response> | null;
  importRequestHandler: ((stage: "preview" | "apply") => Response) | null;
  publishRequest: Deferred<Response> | null;
  publishRequestHandler: ((stage: "validate" | "publish") => Response | Promise<Response>) | null;
}

function createState(): PositionMaintenanceTestState {
  return {
    // 嵌套数组与差异计数也必须隔离，不能只复制基础数据的外层对象。
    draftResponse: structuredClone(baseDraft),
    rowsResponse: { rows: [structuredClone(baseRow)], total: 1, offset: 0, limit: 20 },
    validationResponse: structuredClone(baseValidation),
    failEntry: false,
    entryRequest: null,
    metadataRequest: null,
    metadataResponse: null,
    conflictNextRowWrite: false,
    localConflictNextRowWrite: false,
    expireImportApply: false,
    duplicatePublishNameOnce: false,
    rowRequestHandler: null,
    rowWriteRequest: null,
    singleDeleteRequest: null,
    bulkDeleteRequest: null,
    discardRequest: null,
    importApplyRequest: null,
    importRequestHandler: null,
    publishRequest: null,
    publishRequestHandler: null
  };
}

function createRowResponse(state: PositionMaintenanceTestState) {
  if (state.rowWriteRequest) return state.rowWriteRequest.promise;
  if (state.localConflictNextRowWrite) {
    state.localConflictNextRowWrite = false;
    return jsonResponse({ detail: "记录当前不可复制，请修正后重试" }, 409);
  }
  if (state.conflictNextRowWrite) {
    state.conflictNextRowWrite = false;
    return jsonResponse({ detail: "草稿状态已更新", code: "draft_revision_conflict" }, 409);
  }
  return jsonResponse({ row: { ...baseRow, id: 102, change_type: "added" }, revision: 4 }, 201);
}

function publishResponse(state: PositionMaintenanceTestState) {
  if (state.publishRequestHandler) return state.publishRequestHandler("publish");
  if (state.publishRequest) return state.publishRequest.promise;
  if (state.duplicatePublishNameOnce) {
    state.duplicatePublishNameOnce = false;
    return jsonResponse({ detail: "请更换版本名称", code: "input_version_name_exists" }, 409);
  }
  return jsonResponse(
    {
      ...basePositionVersion,
      id: 32,
      name: "position-20260721",
      original_name: "position-20260721.xlsx",
      draft_revision: 4,
      draft_status: "published"
    },
    201
  );
}

function createRequestHandlers(state: PositionMaintenanceTestState) {
  const draftPath = `/api/input-drafts/${baseDraft.id}`;
  const rowPath = `${draftPath}/rows/${baseRow.id}`;
  const handlers: Partial<Record<string, (url: string) => Response | Promise<Response>>> = {
    "POST /api/input-drafts/position": () => {
      if (state.entryRequest) return state.entryRequest.promise;
      if (state.failEntry) return jsonResponse({ detail: "草稿服务暂时不可用" }, 500);
      return jsonResponse(state.draftResponse);
    },
    "GET /api/input-drafts/position": () =>
      state.metadataRequest?.promise ?? jsonResponse(state.metadataResponse ?? state.draftResponse),
    [`GET ${draftPath}/rows`]: (url) => {
      if (state.rowRequestHandler) return state.rowRequestHandler(url);
      return jsonResponse(state.rowsResponse);
    },
    [`POST ${draftPath}/rows`]: () => createRowResponse(state),
    [`PUT ${rowPath}`]: () =>
      jsonResponse({ row: { ...baseRow, stocking_position: "不备货", change_type: "modified" }, revision: 8 }),
    [`DELETE ${rowPath}`]: () => state.singleDeleteRequest?.promise ?? jsonResponse({ row_id: 101, revision: 9 }),
    [`POST ${draftPath}/rows/bulk-delete`]: () =>
      state.bulkDeleteRequest?.promise ?? jsonResponse({ deleted_ids: [101], revision: 5 }),
    [`POST ${draftPath}/import-preview`]: () =>
      state.importRequestHandler?.("preview") ?? jsonResponse(baseImportPreview),
    [`POST ${draftPath}/import-apply`]: () => {
      if (state.importApplyRequest) return state.importApplyRequest.promise;
      if (state.importRequestHandler) return state.importRequestHandler("apply");
      if (state.expireImportApply)
        return jsonResponse({ detail: "请重新上传表格预览", code: "draft_import_preview_expired" }, 409);
      return jsonResponse({ diff: baseImportPreview.diff, revision: 6 });
    },
    [`POST ${draftPath}/validate`]: () => {
      if (state.publishRequestHandler) return state.publishRequestHandler("validate");
      return jsonResponse(state.validationResponse);
    },
    [`POST ${draftPath}/publish`]: () => publishResponse(state),
    [`POST ${draftPath}/discard`]: () =>
      state.discardRequest?.promise ?? jsonResponse({ ...state.draftResponse, status: "discarded", revision: 4 })
  };
  return handlers;
}

export function createPositionMaintenanceTestEnvironment() {
  const state = createState();
  const handlers = createRequestHandlers(state);
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const handler = handlers[`${method} ${new URL(url, "http://test").pathname}`];
    if (!handler) throw new Error(`Unexpected request: ${method} ${url}`);
    return handler(url);
  });

  return {
    state,
    fetch: fetchMock,
    requests: (method: string, suffix: string) =>
      fetchMock.mock.calls.filter(
        ([input, init]) => String(input).includes(suffix) && (init?.method ?? "GET") === method
      ),
    install: () => vi.stubGlobal("fetch", fetchMock),
    dispose: () => {
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    }
  };
}
