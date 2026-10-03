import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import type { User } from "../types";
import { jsonResponse } from "../pages/admin/positionDraftTestSupport";
import "../styles.css";

export const adminUser: User = { id: 1, username: "admin", role: "admin", active: true };
export const operatorUser: User = { id: 2, username: "operator", role: "operator", active: true };

export function submitLogin(username: string, password: string) {
  fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: username } });
  fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
}

export const routeBatch = {
  id: 7,
  name: "路由测试批次",
  status: "succeeded",
  created_by: 1,
  version_ids: {},
  overreceipt_rule: null,
  versions: {},
  jobs: {},
  error_message: null,
  download_ready: false,
  merged_download_ready: false,
  created_at: "2026-07-21T08:00:00",
  updated_at: "2026-07-21T09:00:00",
  file_count: 0,
  summary: {
    delivery_total: 0,
    import_total: 0,
    manual_total: 0,
    conserved: true
  },
  files: []
};

export const readyInputVersions = ["purchase", "product", "supplier", "position", "template"].map((kind, index) => ({
  id: index + 1,
  kind,
  name: `${kind}-v1`,
  original_name: `${kind}.xlsx`,
  active: true,
  created_by: 1,
  created_at: "2026-08-26T08:00:00"
}));

export function setupAppTests() {
  const state: { authenticatedUser: User | null } = { authenticatedUser: null };
  beforeEach(() => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    localStorage.clear();
    sessionStorage.clear();
    state.authenticatedUser = null;
    window.history.replaceState({}, "", "/");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/auth/me")) {
          return jsonResponse(state.authenticatedUser ?? { detail: "未登录" }, state.authenticatedUser ? 200 : 401);
        }
        if (url.endsWith("/api/auth/login")) {
          return jsonResponse(
            {
              token: "token-1",
              user: { id: 1, username: "admin", role: "admin", active: true }
            },
            200
          );
        }
        if (url.endsWith("/api/auth/logout")) {
          return new Response(null, { status: 204 });
        }
        if (url.endsWith("/api/batches/7/exceptions/filters")) {
          return jsonResponse({ reasons: [], sites: [], scales: [], stocking: [] }, 200);
        }
        if (url.includes("/api/batches/7/exceptions?")) {
          return jsonResponse(
            {
              items: [],
              total: 0,
              stats: { unfinished_count: 0, unfinished_quantity: 0, resolved_count: 0, total_count: 0 }
            },
            200
          );
        }
        if (url.endsWith("/api/batches/7")) {
          return jsonResponse(routeBatch, 200);
        }
        if (url.includes("/api/batches?")) {
          return jsonResponse({ items: [routeBatch], total: 1, empty_draft_count: 0 }, 200);
        }
        if (url.endsWith("/api/input-versions")) {
          return jsonResponse([], 200);
        }
        if (url.endsWith("/api/purchase-sync")) {
          return jsonResponse({ configured: true, job: null }, 200);
        }
        if (url.endsWith("/api/self-operated-inbound-sync")) {
          return jsonResponse({ configured: true, job: null, active_version: null }, 200);
        }
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions")) {
          return jsonResponse([], 200);
        }
        if (url.endsWith("/api/overreceipt-rule-versions")) {
          return jsonResponse([], 200);
        }
        if (url.endsWith("/api/overreceipt-rule-versions/warehouses")) {
          return jsonResponse([], 200);
        }
        if (url.endsWith("/api/users") || url.endsWith("/api/audit-logs")) {
          return jsonResponse([], 200);
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  return state;
}
