import { render as renderComponent } from "@testing-library/react";
import { App as AntApp } from "antd";
import type { ReactElement } from "react";
import { afterEach, beforeEach, vi } from "vitest";
import type { AuditLog, InputVersion, User } from "../../types";
import type { Deferred } from "./positionDraftTestSupport";
import { baseDraft, basePositionVersion, baseValidation, jsonResponse } from "./positionDraftTestSupport";

export const render = (ui: ReactElement) => renderComponent(ui, { wrapper: AntApp });
export const admin: User = { id: 1, username: "admin", role: "admin", active: true };
export const operator: User = { id: 2, username: "operator", role: "operator", active: true };
export const positionVersion = basePositionVersion;

export function requestCount(method: string, suffix: string): number {
  return vi
    .mocked(fetch)
    .mock.calls.filter(([input, init]) => String(input).endsWith(suffix) && (init?.method ?? "GET") === method).length;
}

interface AdminTestState {
  users: User[];
  versions: InputVersion[];
  auditLogs: AuditLog[];
  positionFlow: boolean;
  positionEntryRequest: Deferred<Response> | null;
}

export function setupAdminTests() {
  const state: AdminTestState = {
    users: [],
    versions: [],
    auditLogs: [],
    positionFlow: false,
    positionEntryRequest: null
  };
  beforeEach(() => {
    state.users = [admin, operator];
    state.versions = [];
    state.auditLogs = [
      {
        id: 1,
        user_id: null,
        action: "worker_compute_succeeded",
        entity_type: "batch",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:00:00"
      }
    ];
    state.positionFlow = false;
    state.positionEntryRequest = null;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/api/auth/me")) return jsonResponse(admin);

        if (url.endsWith("/api/users") && method === "GET") return jsonResponse(state.users);
        if (url.endsWith("/api/users") && method === "POST") {
          const payload = JSON.parse(String(init?.body)) as { username: string; role: User["role"] };
          const created = { id: 3, username: payload.username, role: payload.role, active: true };
          state.users = [...state.users, created];
          return jsonResponse(created, 201);
        }
        if (/\/api\/users\/\d+\/status$/.test(url) && method === "PUT") {
          const id = Number(url.match(/\/api\/users\/(\d+)\/status$/)?.[1]);
          const payload = JSON.parse(String(init?.body)) as { active: boolean };
          state.users = state.users.map((user) => (user.id === id ? { ...user, active: payload.active } : user));
          return jsonResponse(state.users.find((user) => user.id === id));
        }
        if (/\/api\/users\/\d+\/password$/.test(url) && method === "PUT") {
          return new Response(null, { status: 204 });
        }

        if (url.endsWith("/api/input-versions") && method === "GET") return jsonResponse(state.versions);
        if (url.endsWith("/api/input-versions/31/inspection")) {
          return jsonResponse({
            summary: {
              kind: "position",
              row_count: 1,
              columns: ["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位"],
              metrics: { sites: 1, skus: 1, mskus: 1 },
              issues: []
            },
            preview: {
              kind: "position",
              columns: ["店铺-站点", "积加SKU", "MSKU"],
              rows: [{ "店铺-站点": "SEEKWAY:US", 积加SKU: "SKU-A", MSKU: "MSKU-A" }],
              total: 1,
              offset: 0,
              limit: 20
            }
          });
        }

        if (url.endsWith("/api/audit-logs") && method === "GET") {
          return jsonResponse(state.auditLogs);
        }
        if (url.endsWith("/api/admin/integrations/gerpgo") && method === "GET") {
          return jsonResponse({
            configured: false,
            base_url: "https://open.gerpgo.com/api/open",
            app_id_hint: "",
            has_app_id: false,
            has_app_key: false,
            source: "environment"
          });
        }

        if (state.positionFlow && url.endsWith("/api/input-drafts/position") && method === "POST") {
          if (state.positionEntryRequest) return state.positionEntryRequest.promise;
          return jsonResponse({ ...baseDraft, updated_by: 1 });
        }
        if (state.positionFlow && url.includes("/api/input-drafts/7/rows?") && method === "GET") {
          return jsonResponse({ rows: [], total: 0, offset: 0, limit: 20 });
        }
        if (state.positionFlow && url.endsWith("/api/input-drafts/7/validate") && method === "POST") {
          return jsonResponse(baseValidation);
        }
        if (state.positionFlow && url.endsWith("/api/input-drafts/7/publish") && method === "POST") {
          const published = {
            ...positionVersion,
            id: 32,
            name: "position-published",
            original_name: "position-published.xlsx",
            draft_revision: 4,
            draft_status: "published"
          };
          state.versions = [published];
          return jsonResponse(published, 201);
        }

        throw new Error(`Unexpected request: ${method} ${url}`);
      })
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  return state;
}
