import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { message } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as apiModule from "../api";
import type { AuditLog, InputVersion, User } from "../types";
import AdminPage from "./AdminPage";
import { AuditLogPanel } from "./admin/AuditLogPanel";
import { UserManagementPanel } from "./admin/UserManagementPanel";

const jsonResponse = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "Content-Type": "application/json" }
});

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

const admin: User = { id: 1, username: "admin", role: "admin", active: true };
const operator: User = { id: 2, username: "operator", role: "operator", active: true };
const positionVersion: InputVersion = {
  id: 31,
  kind: "position",
  name: "position-current",
  original_name: "position-current.xlsx",
  active: true,
  created_by: 1,
  created_at: "2026-07-21T09:00:00"
};

let users: User[];
let versions: InputVersion[];
let auditLogs: AuditLog[];
let positionFlow: boolean;
let positionEntryRequest: Deferred<Response> | null;

function requestCount(method: string, suffix: string): number {
  return vi.mocked(fetch).mock.calls.filter(([input, init]) =>
    String(input).endsWith(suffix) && (init?.method ?? "GET") === method
  ).length;
}

describe("AdminPage", () => {
  beforeEach(() => {
    users = [admin, operator];
    versions = [];
    auditLogs = [{
      id: 1,
      user_id: null,
      action: "worker_compute_succeeded",
      entity_type: "batch",
      entity_id: "7",
      details: {},
      created_at: "2026-07-21T09:00:00"
    }];
    positionFlow = false;
    positionEntryRequest = null;
    vi.spyOn(message, "success").mockImplementation(() => {
      const result = (() => undefined) as ReturnType<typeof message.success>;
      const completed = Promise.resolve(true);
      result.then = completed.then.bind(completed);
      return result;
    });

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/api/users") && method === "GET") return jsonResponse(users);
      if (url.endsWith("/api/users") && method === "POST") {
        const payload = JSON.parse(String(init?.body)) as { username: string; role: User["role"] };
        const created = { id: 3, username: payload.username, role: payload.role, active: true };
        users = [...users, created];
        return jsonResponse(created, 201);
      }
      if (/\/api\/users\/\d+\/status$/.test(url) && method === "PUT") {
        const id = Number(url.match(/\/api\/users\/(\d+)\/status$/)?.[1]);
        const payload = JSON.parse(String(init?.body)) as { active: boolean };
        users = users.map((user) => user.id === id ? { ...user, active: payload.active } : user);
        return jsonResponse(users.find((user) => user.id === id));
      }
      if (/\/api\/users\/\d+\/password$/.test(url) && method === "PUT") {
        return new Response(null, { status: 204 });
      }

      if (url.endsWith("/api/input-versions") && method === "GET") return jsonResponse(versions);
      if (url.endsWith("/api/input-versions/31/inspection")) {
        return jsonResponse({
          summary: {
            kind: "position",
            row_count: 1,
            columns: ["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位", "已下单可售天数"],
            metrics: { sites: 1, skus: 1, mskus: 1 },
            issues: []
          },
          preview: {
            kind: "position",
            columns: ["店铺-站点", "积加SKU", "MSKU"],
            rows: [{ "店铺-站点": "SEEKWAY:US", "积加SKU": "SKU-A", MSKU: "MSKU-A" }],
            total: 1,
            offset: 0,
            limit: 20
          }
        });
      }

      if (url.endsWith("/api/audit-logs") && method === "GET") {
        return jsonResponse(auditLogs);
      }
      if (
        url.endsWith("/api/admin/integrations/gerpgo")
        && method === "GET"
      ) {
        return jsonResponse({
          configured: false,
          base_url: "https://openapi.gerpgo.com",
          app_id_hint: "",
          has_app_id: false,
          has_app_key: false,
          source: "environment"
        });
      }



      if (positionFlow && url.endsWith("/api/input-drafts/position") && method === "POST") {
        if (positionEntryRequest) return positionEntryRequest.promise;
        return jsonResponse({
          id: 7,
          kind: "position",
          base_version_id: 31,
          base_version_name: "position-current",
          active_version_id: 31,
          active_version_name: "position-current",
          status: "editing",
          revision: 3,
          created_by: 1,
          updated_by: 1,
          created_at: "2026-07-21T09:10:00",
          updated_at: "2026-07-21T10:30:00",
          row_count: 1,
          modified_count: 0,
          diff: { added: 0, modified: 0, deleted: 0, unchanged: 1 },
          issues: [],
          error_count: 0,
          warning_count: 0,
          valid: true
        });
      }
      if (positionFlow && url.includes("/api/input-drafts/7/rows?") && method === "GET") {
        return jsonResponse({ rows: [], total: 0, offset: 0, limit: 20 });
      }
      if (positionFlow && url.endsWith("/api/input-drafts/7/validate") && method === "POST") {
        return jsonResponse({
          draft_id: 7,
          revision: 3,
          diff: { added: 0, modified: 0, deleted: 0, unchanged: 1 },
          issues: [],
          error_count: 0,
          warning_count: 0,
          valid: true
        });
      }
      if (positionFlow && url.endsWith("/api/input-drafts/7/publish") && method === "POST") {
        const published = {
          ...positionVersion,
          id: 32,
          name: "position-published",
          original_name: "position-published.xlsx",
          draft_revision: 4,
          draft_status: "published"
        };
        versions = [published];
        return jsonResponse(published, 201);
      }

      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not render administrator content before the initial data is ready", async () => {
    const pendingVersions = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/input-versions") return pendingVersions.promise;
      throw new Error(`Unexpected request: GET ${url.pathname}`);
    }));

    render(<AdminPage currentUser={admin} />);

    expect(screen.getByLabelText("正在加载管理员维护")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "管理员维护" })).not.toBeInTheDocument();
    expect(screen.queryByText("基础资料目录")).not.toBeInTheDocument();

    await act(async () => {
      pendingVersions.resolve(jsonResponse(versions));
      await Promise.resolve();
    });

    expect(await screen.findByRole("heading", { name: "管理员维护" })).toBeInTheDocument();
    expect(screen.getByText("基础资料目录")).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);
  });
  it("loads administrator resources only when their tab is opened", async () => {
    render(<AdminPage currentUser={admin} />);

    expect(await screen.findByText("基础资料目录")).toBeInTheDocument();
    expect(requestCount("GET", "/api/input-versions")).toBe(1);
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "接口配置" }));
    expect(await screen.findByText("积加开放平台")).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    expect(await screen.findByText("内部账号")).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(1);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    expect(await screen.findByText("最多显示 200 条")).toBeInTheDocument();

    expect(requestCount("GET", "/api/users")).toBe(1);
    expect(requestCount("GET", "/api/input-versions")).toBe(1);
    expect(requestCount("GET", "/api/audit-logs")).toBe(1);
    expect(requestCount("GET", "/api/admin/integrations/gerpgo")).toBe(1);
    expect(requestCount("GET", "/api/purchase-sync")).toBe(0);
  });

  it("offers labelled audit filters and a clear result count", () => {
    const records: AuditLog[] = [
      {
        id: 1,
        user_id: 1,
        action: "create_user",
        entity_type: "user",
        entity_id: "2",
        details: {},
        created_at: "2026-07-21T09:00:00"
      },
      {
        id: 2,
        user_id: null,
        action: "worker_compute_failed",
        entity_type: "batch",
        entity_id: "7",
        details: {},
        created_at: "2026-07-21T09:10:00"
      },
      {
        id: 3,
        user_id: 2,
        action: "publish_overreceipt_rule",
        entity_type: "overreceipt_rule",
        entity_id: "4",
        details: {},
        created_at: "2026-07-21T09:20:00"
      }
    ];
    render(<AuditLogPanel auditLogs={records} users={[admin, operator]} loading={false} error={null} onRetry={vi.fn()} />);

    expect(screen.getByRole("table", { name: "操作记录" })).toBeInTheDocument();
    expect(screen.getByText("搜索", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("操作类型", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("操作人", { selector: "label" })).toBeInTheDocument();
    expect(screen.getByText("显示 3 / 3 条")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索操作记录"), { target: { value: "批次 #7" } });
    expect(screen.getByText("显示 1 / 3 条")).toBeInTheDocument();
    expect(screen.getByText("计算失败")).toBeInTheDocument();
    expect(screen.queryByText("创建用户")).not.toBeInTheDocument();
  });

  it("translates self-operated sync audit values", () => {
    const records: AuditLog[] = [{
      id: 4,
      user_id: null,
      action: "self_operated_inbound_sync_succeeded",
      entity_type: "self_operated_inbound_sync_job",
      entity_id: "12",
      details: {},
      created_at: "2026-07-21T09:30:00"
    }];

    render(
      <AuditLogPanel
        auditLogs={records}
        users={[admin, operator]}
        loading={false}
        error={null}
        onRetry={vi.fn()}
      />
    );

    expect(screen.getByText("待入库数据同步完成")).toBeInTheDocument();
    expect(screen.getByText("待入库同步任务 #12")).toBeInTheDocument();

  });
  it("keeps only the latest StrictMode version results when earlier requests settle last", async () => {
    const staleVersions = deferred<Response>();
    const freshVersions = deferred<Response>();
    const freshPosition = { ...positionVersion, name: "position-fresh" };
    const responses = [staleVersions, freshVersions];

    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname !== "/api/input-versions") {
        throw new Error(`Unexpected request: GET ${url.pathname}`);
      }
      const request = responses.shift();
      if (!request) throw new Error(`Unexpected request: GET ${url.pathname}`);
      return request.promise;
    }));

    render(<StrictMode><AdminPage currentUser={admin} /></StrictMode>);
    await waitFor(() => {
      expect(requestCount("GET", "/api/input-versions")).toBe(2);
    });
    freshVersions.resolve(jsonResponse([freshPosition]));
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    staleVersions.resolve(jsonResponse([{ ...positionVersion, name: "position-stale" }]));
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    await waitFor(() => expect(screen.getByRole("button", {
      name: /MSKU定位，已就绪，当前版本 position-fresh/
    })).toBeInTheDocument());
    expect(screen.queryByRole("button", {
      name: /MSKU定位，已就绪，当前版本 position-stale/
    })).not.toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);
  });

  it("ignores deferred administrator responses after unmount", async () => {
    const pendingVersions = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/input-versions") return pendingVersions.promise;
      throw new Error(`Unexpected request: GET ${url.pathname}`);
    }));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const view = render(<AdminPage currentUser={admin} />);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1));
    view.unmount();
    const errorsBeforeSettling = consoleError.mock.calls.length;

    await act(async () => {
      pendingVersions.resolve(jsonResponse([positionVersion]));
      await Promise.resolve();
    });

    expect(consoleError.mock.calls).toHaveLength(errorsBeforeSettling);
  });

  it("opens position maintenance in place and returns focus to the input catalog", async () => {
    versions = [positionVersion];
    positionFlow = true;
    render(<AdminPage currentUser={admin} />);

    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
    const maintenanceEntry = screen.getByRole("button", { name: "开始网页维护" });
    fireEvent.click(maintenanceEntry);
    expect(await screen.findByText("MSKU 定位维护")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "返回基础资料" })).toHaveFocus());

    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    await waitFor(() => expect(screen.queryByText("MSKU 定位维护")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "基础资料目录" })).toHaveFocus();
  }, 30_000);

  it("returns from position entry loading and restores focus to the input catalog", async () => {
    versions = [positionVersion];
    positionFlow = true;
    positionEntryRequest = deferred<Response>();
    const view = render(<AdminPage currentUser={admin} />);

    try {
      await screen.findByText("基础资料目录");
      fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
      fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
      expect(await screen.findByText("正在创建或恢复服务器草稿")).toBeInTheDocument();
      await waitFor(() => expect(screen.getByRole("button", { name: "返回基础资料" })).toHaveFocus());

      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      await waitFor(() => expect(screen.getByRole("heading", { name: "基础资料目录" })).toHaveFocus());
    } finally {
      view.unmount();
      positionEntryRequest?.resolve(jsonResponse({}));
    }
  });

  it("refreshes only versions and returns to the catalog after position publish", async () => {
    versions = [positionVersion];
    positionFlow = true;
    render(<AdminPage currentUser={admin} />);

    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    fireEvent.change(await screen.findByLabelText("新版本名称"), { target: { value: "position-published" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));

    await waitFor(() => expect(requestCount("GET", "/api/input-versions")).toBe(2));
    await waitFor(() => expect(screen.queryByText("MSKU 定位维护")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /MSKU定位，已就绪，当前版本 position-published/ })).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);
  }, 30_000);

  it("keeps the current administrator self-disable action blocked", async () => {
    render(
      <UserManagementPanel
        currentUser={admin}
        users={users}
        loading={false}
        error={null}
        onDataChanged={vi.fn()}
      />
    );

    const adminRow = screen.getByText("admin").closest("tr");
    expect(adminRow).not.toBeNull();
    expect(screen.getByRole("table", { name: "内部账号" })).toBeInTheDocument();
    expect(screen.getByText("共 2 个账号")).toBeInTheDocument();
    expect(screen.getByText("1 个管理员")).toBeInTheDocument();
    expect(screen.getByText("1 个操作员")).toBeInTheDocument();
    expect(within(adminRow!).getByRole("button", { name: "停用 admin" })).toBeDisabled();
    expect(within(adminRow!).getByText("当前账号不可停用")).toBeInTheDocument();
  });

  it("creates an internal user and reloads the shared administrator data", async () => {
    const onDataChanged = vi.fn();
    render(
      <UserManagementPanel
        currentUser={admin}
        users={users}
        loading={false}
        error={null}
        onDataChanged={onDataChanged}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "创建用户" }));
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "reviewer" } });
    fireEvent.change(screen.getByLabelText("初始密码"), { target: { value: "reviewer-pass" } });
    expect(screen.getByRole("button", { name: "取消" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(requestCount("POST", "/api/users")).toBe(1));
    expect(onDataChanged).toHaveBeenCalledOnce();
    const request = vi.mocked(fetch).mock.calls.find(([input, init]) =>
      String(input).endsWith("/api/users") && init?.method === "POST"
    );
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      username: "reviewer",
      password: "reviewer-pass",
      role: "operator"
    });
  });

  it("disables an operator through the existing status endpoint", async () => {
    const onDataChanged = vi.fn();
    render(
      <UserManagementPanel
        currentUser={admin}
        users={users}
        loading={false}
        error={null}
        onDataChanged={onDataChanged}
      />
    );

    const operatorRow = screen.getByText("operator").closest("tr")!;
    fireEvent.click(within(operatorRow).getByRole("button", { name: "停用 operator" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认停用" }));
    await waitFor(() => expect(requestCount("PUT", "/api/users/2/status")).toBe(1));
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls.find(([input]) =>
      String(input).endsWith("/api/users/2/status")
    )?.[1]?.body))).toEqual({ active: false });
    expect(onDataChanged).toHaveBeenCalledOnce();
  });

  it("resets an operator password through the existing password endpoint", async () => {
    const onDataChanged = vi.fn();
    render(
      <UserManagementPanel
        currentUser={admin}
        users={users}
        loading={false}
        error={null}
        onDataChanged={onDataChanged}
      />
    );

    fireEvent.click(within(screen.getByText("operator").closest("tr")!).getByRole("button", { name: "重置密码 operator" }));
    const dialog = await screen.findByRole("dialog", { name: "重置密码 · operator" });
    fireEvent.change(within(dialog).getByLabelText("新密码"), { target: { value: "operator-new-pass" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "重置密码" }));
    await waitFor(() => expect(requestCount("PUT", "/api/users/2/password")).toBe(1));
    const request = vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/users/2/password"));
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ password: "operator-new-pass" });
    expect(onDataChanged).toHaveBeenCalledOnce();
  }, 30_000);

  it("expires the current session after resetting the current administrator password", async () => {
    const onDataChanged = vi.fn();
    const expireSession = vi.spyOn(apiModule, "expireSession").mockImplementation(() => undefined);
    render(
      <UserManagementPanel
        currentUser={admin}
        users={users}
        loading={false}
        error={null}
        onDataChanged={onDataChanged}
      />
    );

    fireEvent.click(within(screen.getByText("admin").closest("tr")!).getByRole("button", { name: "重置密码 admin" }));
    const dialog = await screen.findByRole("dialog", { name: "重置密码 · admin" });
    fireEvent.change(within(dialog).getByLabelText("新密码"), { target: { value: "admin-new-pass" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "重置密码" }));

    await waitFor(() => expect(requestCount("PUT", "/api/users/1/password")).toBe(1));
    expect(expireSession).toHaveBeenCalledWith("密码已重置，请使用新密码重新登录");
    expect(onDataChanged).not.toHaveBeenCalled();
  });

  it("shows draft audit labels and resolves operator names", async () => {
    auditLogs = [
      { id: 8, user_id: 2, action: "activate_overreceipt_rule", entity_type: "overreceipt_rule", entity_id: "9", details: {}, created_at: "2026-07-21T09:07:00" },
      { id: 7, user_id: 2, action: "publish_overreceipt_rule", entity_type: "overreceipt_rule", entity_id: "9", details: {}, created_at: "2026-07-21T09:06:00" },
      { id: 6, user_id: 1, action: "activate_input_version", entity_type: "input_version", entity_id: "32", details: {}, created_at: "2026-07-21T09:05:00" },
      { id: 5, user_id: 1, action: "publish_input_draft", entity_type: "input_draft", entity_id: "7", details: {}, created_at: "2026-07-21T09:04:00" },
      { id: 4, user_id: 1, action: "discard_input_draft", entity_type: "input_draft", entity_id: "7", details: {}, created_at: "2026-07-21T09:03:00" },
      { id: 3, user_id: 2, action: "import_input_draft", entity_type: "input_draft", entity_id: "7", details: {}, created_at: "2026-07-21T09:02:00" },
      { id: 2, user_id: 2, action: "create_input_draft", entity_type: "input_draft", entity_id: "7", details: {}, created_at: "2026-07-21T09:01:00" },
      { id: 1, user_id: 2, action: "resume_input_draft", entity_type: "input_draft", entity_id: "7", details: {}, created_at: "2026-07-21T09:00:00" }
    ];
    render(<AuditLogPanel auditLogs={auditLogs} users={users} loading={false} error={null} onRetry={vi.fn()} />);

    expect(await screen.findByText("创建库位草稿")).toBeInTheDocument();
    expect(screen.getByText("导入库位草稿")).toBeInTheDocument();
    expect(screen.getByText("放弃库位草稿")).toBeInTheDocument();
    expect(screen.getByText("发布库位版本")).toBeInTheDocument();
    expect(screen.getByText("启用输入版本")).toBeInTheDocument();
    expect(screen.getByText("继续库位草稿")).toBeInTheDocument();
    expect(screen.getByText("发布超收规则")).toBeInTheDocument();
    expect(screen.getByText("启用超收规则")).toBeInTheDocument();
    expect(screen.queryByText("resume_input_draft")).not.toBeInTheDocument();
    expect(screen.getAllByText("operator").length).toBeGreaterThan(0);
  });

  it("shows audit loading, empty, and error feedback", async () => {
    const { rerender } = render(
      <AuditLogPanel auditLogs={[]} users={users} loading error={null} onRetry={vi.fn()} />
    );
    expect(screen.getByText("正在读取操作记录")).toBeInTheDocument();

    rerender(<AuditLogPanel auditLogs={[]} users={users} loading={false} error={null} onRetry={vi.fn()} />);
    expect(await screen.findByText("暂无操作记录")).toBeInTheDocument();
  });

  it("keeps audit failures inside the operation history panel", async () => {
    render(
      <AuditLogPanel
        auditLogs={[]}
        users={users}
        loading={false}
        error="审计服务暂时不可用"
        onRetry={vi.fn()}
      />
    );

    expect(await screen.findByText("无法读取操作记录")).toBeInTheDocument();
    expect(screen.getByText("审计服务暂时不可用")).toBeInTheDocument();
  });
});
