import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { message } from "antd";
import { describe, expect, it, vi } from "vitest";
import * as apiModule from "../../api";
import AdminPage from "../AdminPage";
import { UserManagementPanel } from "./UserManagementPanel";
import { admin, operator, render, requestCount, setupAdminTests } from "./adminPageTestSupport";
import { jsonResponse } from "./positionDraftTestSupport";

describe("管理员Users", () => {
  const state = setupAdminTests();
  it.each([500, 401])("does not repeat a saved user creation after a %s refresh error", async (status) => {
    await apiModule.api("/api/auth/me");
    const originalFetch = fetch;
    let saved = false;
    let failRefresh = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") saved = true;
        if (saved && failRefresh && String(input).endsWith("/api/users") && !init?.method) {
          return jsonResponse({ detail: status === 401 ? "未登录" : "读取暂不可用" }, status);
        }
        return originalFetch(input, init);
      })
    );
    render(<AdminPage currentUser={admin} />);
    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    await screen.findByText(operator.username);
    fireEvent.click(screen.getByRole("button", { name: "创建用户" }));
    const dialog = await screen.findByRole("dialog", { name: "创建内部用户" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "操作员<&>" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: "synthetic123" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建" }));
    await waitFor(() => expect(dialog).not.toBeVisible());
    expect(screen.queryByText("用户已创建")).not.toBeInTheDocument();
    if (status === 500) {
      expect(await screen.findByText(/变更已保存.*读取暂不可用/)).toBeInTheDocument();
      failRefresh = false;
      fireEvent.click(screen.getByText("重新加载用户账号", { selector: "button > span" }));
      expect(await screen.findByText("操作员<&>")).toBeInTheDocument();
      expect(screen.queryByText("无法读取用户账号")).not.toBeInTheDocument();
    } else {
      expect(screen.queryByText("未登录")).not.toBeInTheDocument();
      expect(screen.queryByText("无法读取用户账号")).not.toBeInTheDocument();
    }
    expect(requestCount("POST", "/api/users")).toBe(1);
  });

  it.each([401, 403, 409, 422, 500])("handles a %s user write failure without losing input", async (status) => {
    await apiModule.api("/api/auth/me");
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === "POST"
          ? Promise.resolve(jsonResponse({ detail: "写入失败" }, status))
          : originalFetch(input, init)
      )
    );
    const changed = vi.fn();
    render(
      <UserManagementPanel
        currentUser={admin}
        users={state.users}
        loading={false}
        error={null}
        onDataChanged={changed}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "创建用户" }));
    const dialog = await screen.findByRole("dialog", { name: "创建内部用户" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "保留输入" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: "synthetic123" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建" }));
    await waitFor(() => expect(requestCount("POST", "/api/users")).toBe(1));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "创建" })).toBeEnabled());
    expect(within(dialog).getByLabelText("用户名")).toHaveValue("保留输入");
    expect(changed).not.toHaveBeenCalled();
    if (status === 401) expect(screen.queryByText("写入失败")).not.toBeInTheDocument();
    else expect(await screen.findByText("写入失败")).toBeInTheDocument();
  });

  it("uses contextual user success feedback", async () => {
    const staticSuccess = vi.spyOn(message, "success");
    render(
      <UserManagementPanel
        currentUser={admin}
        users={state.users}
        loading={false}
        error={null}
        onDataChanged={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "停用 operator" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认停用" }));
    expect(await screen.findByText("用户已停用")).toBeInTheDocument();
    expect(staticSuccess).not.toHaveBeenCalled();
  });

  it("keeps the current administrator self-disable action blocked", async () => {
    render(
      <UserManagementPanel
        currentUser={admin}
        users={state.users}
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
        users={state.users}
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
    const request = vi
      .mocked(fetch)
      .mock.calls.find(([input, init]) => String(input).endsWith("/api/users") && init?.method === "POST");
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
        users={state.users}
        loading={false}
        error={null}
        onDataChanged={onDataChanged}
      />
    );

    const operatorRow = screen.getByText("operator").closest("tr")!;
    fireEvent.click(within(operatorRow).getByRole("button", { name: "停用 operator" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认停用" }));
    await waitFor(() => expect(requestCount("PUT", "/api/users/2/status")).toBe(1));
    expect(
      JSON.parse(
        String(vi.mocked(fetch).mock.calls.find(([input]) => String(input).endsWith("/api/users/2/status"))?.[1]?.body)
      )
    ).toEqual({ active: false });
    expect(onDataChanged).toHaveBeenCalledOnce();
  });

  it("resets an operator password through the existing password endpoint", async () => {
    const onDataChanged = vi.fn();
    render(
      <UserManagementPanel
        currentUser={admin}
        users={state.users}
        loading={false}
        error={null}
        onDataChanged={onDataChanged}
      />
    );

    fireEvent.click(
      within(screen.getByText("operator").closest("tr")!).getByRole("button", { name: "重置密码 operator" })
    );
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
        users={state.users}
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
});
