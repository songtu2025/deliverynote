import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AdminPage from "../AdminPage";
import { admin, operator, positionVersion, render, requestCount, setupAdminTests } from "./adminPageTestSupport";
import { deferred, jsonResponse } from "./positionDraftTestSupport";

describe("管理员页面生命周期", () => {
  const state = setupAdminTests();

  it("隐藏后停止自动读取，重新激活只后台刷新资料并保留标签页", async () => {
    const view = render(<AdminPage currentUser={admin} active />);
    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    await screen.findByText(operator.username);
    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    await screen.findByText("批次 #7");

    view.rerender(<AdminPage currentUser={admin} active={false} />);
    expect(requestCount("GET", "/api/input-versions")).toBe(1);
    expect(requestCount("GET", "/api/users")).toBe(1);
    expect(requestCount("GET", "/api/audit-logs")).toBe(1);
    view.rerender(<AdminPage currentUser={admin} active />);
    await waitFor(() => expect(requestCount("GET", "/api/input-versions")).toBe(2));
    expect(screen.getByRole("tab", { name: "操作记录" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByLabelText("正在加载管理员维护")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    expect(requestCount("GET", "/api/users")).toBe(1);
    expect(requestCount("GET", "/api/audit-logs")).toBe(1);
  });

  it("首次资料读取失败后可以重试恢复", async () => {
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    let failed = false;
    vi.mocked(fetch).mockImplementation((input, init) => {
      if (String(input).endsWith("/api/input-versions") && !failed) {
        failed = true;
        return Promise.resolve(jsonResponse({ detail: "合成资料读取失败" }, 500));
      }
      return originalFetch(input, init);
    });
    render(<AdminPage currentUser={admin} />);
    await screen.findByText("合成资料读取失败");
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await waitFor(() => expect(screen.queryByText("无法读取基础资料")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "基础资料目录" })).toBeVisible();
    expect(requestCount("GET", "/api/input-versions")).toBe(2);
    expect(requestCount("GET", "/api/users")).toBe(0);
  });

  it("用户响应乱序时保留最新账号列表", async () => {
    const oldUsers = deferred<Response>();
    const newUsers = deferred<Response>();
    const pending = [oldUsers, newUsers];
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation((input, init) =>
      String(input).endsWith("/api/users") ? pending.shift()!.promise : originalFetch(input, init)
    );
    render(<AdminPage currentUser={admin} />);
    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    await waitFor(() => expect(requestCount("GET", "/api/users")).toBe(1));
    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    await waitFor(() => expect(requestCount("GET", "/api/users")).toBe(2));
    await act(async () => newUsers.resolve(jsonResponse([admin, { ...operator, username: "最新账号" }])));
    await act(async () => oldUsers.resolve(jsonResponse([admin, { ...operator, username: "旧账号" }])));
    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    expect(await screen.findByText("最新账号")).toBeVisible();
    expect(screen.queryByText("旧账号")).not.toBeInTheDocument();
  });

  it("审计响应乱序时保留最新记录", async () => {
    const oldAudit = deferred<Response>();
    const newAudit = deferred<Response>();
    const pending = [oldAudit, newAudit];
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation((input, init) =>
      String(input).endsWith("/api/audit-logs") ? pending.shift()!.promise : originalFetch(input, init)
    );
    const view = render(<AdminPage currentUser={admin} active />);
    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    await waitFor(() => expect(requestCount("GET", "/api/audit-logs")).toBe(1));
    view.rerender(<AdminPage currentUser={admin} active={false} />);
    view.rerender(<AdminPage currentUser={admin} active />);
    await waitFor(() => expect(requestCount("GET", "/api/audit-logs")).toBe(2));
    await act(async () => newAudit.resolve(jsonResponse([{ ...state.auditLogs[0], entity_id: "202" }])));
    await act(async () => oldAudit.resolve(jsonResponse([{ ...state.auditLogs[0], entity_id: "101" }])));
    expect(await screen.findByText("批次 #202")).toBeVisible();
    expect(screen.queryByText("批次 #101")).not.toBeInTheDocument();
  });

  it.each(["/api/users", "/api/audit-logs"])("卸载后忽略 %s 的迟到响应", async (endpoint) => {
    const pending = deferred<Response>();
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.mocked(fetch).mockImplementation((input, init) =>
      String(input).endsWith(endpoint) ? pending.promise : originalFetch(input, init)
    );
    const view = render(<AdminPage currentUser={admin} />);
    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    await waitFor(() => expect(requestCount("GET", endpoint)).toBe(1));
    view.unmount();
    const errorsBefore = consoleError.mock.calls.length;
    await act(async () => pending.resolve(jsonResponse(endpoint === "/api/users" ? state.users : state.auditLogs)));
    expect(screen.queryByRole("heading", { name: "管理员维护" })).not.toBeInTheDocument();
    expect(consoleError.mock.calls.length).toBe(errorsBefore);
    expect(requestCount("GET", endpoint)).toBe(1);
  });

  it("返回目录后立即卸载，不干扰后续界面的焦点", async () => {
    state.versions = [positionVersion];
    state.positionFlow = true;
    const view = render(<AdminPage currentUser={admin} />);
    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    fireEvent.click(await screen.findByRole("button", { name: "返回基础资料" }));
    view.unmount();
    render(<button autoFocus>后续界面</button>);
    await act(async () => new Promise((resolve) => window.setTimeout(resolve, 0)));
    expect(screen.getByRole("button", { name: "后续界面" })).toHaveFocus();
  });
});
