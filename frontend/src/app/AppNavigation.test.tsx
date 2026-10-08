import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { setupAppTests, adminUser, operatorUser, routeBatch, readyInputVersions } from "./appTestSupport";
import App from "../App";

describe("AppNavigation", () => {
  const state = setupAppTests();
  it("redirects an operator's admin URL without loading admin data", async () => {
    state.authenticatedUser = operatorUser;
    window.history.replaceState({}, "", "/admin");
    render(<App />);
    await screen.findByText("交货批次", { selector: "h2" });
    expect(window.location.pathname).toBe("/batches");
    expect(screen.queryByRole("menuitem", { name: /管理员维护/ })).not.toBeInTheDocument();
    const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls).not.toContain("/api/users");
    expect(requestedUrls).not.toContain("/api/audit-logs");
  });

  it("canonicalizes a batch detail URL with trailing slashes", async () => {
    state.authenticatedUser = adminUser;
    window.history.replaceState({}, "", "/batches/7///");
    render(<App />);
    await screen.findByRole("heading", { name: "路由测试批次" });
    expect(window.location.pathname).toBe("/batches/7");
  });

  it("canonicalizes an unknown path to the delivery workspace", async () => {
    state.authenticatedUser = adminUser;
    window.history.replaceState({}, "", "/unknown-workspace");
    render(<App />);
    await screen.findByRole("heading", { name: "交货批次" });
    expect(window.location.pathname).toBe("/batches");
  });

  it("restores an inbound detail and returns to its own list", async () => {
    state.authenticatedUser = adminUser;
    window.history.replaceState({}, "", "/self-operated/7");
    render(<App />);
    await screen.findByRole("heading", { name: "路由测试批次" });
    expect(window.location.pathname).toBe("/self-operated/7");
    fireEvent.click(screen.getByRole("button", { name: /返回批次列表/ }));
    await screen.findByRole("heading", { name: "自营仓入库" });
    expect(window.location.pathname).toBe("/self-operated");
  });

  it("restores both workspaces when browser history moves back and forward", async () => {
    state.authenticatedUser = adminUser;
    render(<App />);
    await screen.findByRole("heading", { name: "交货批次" });
    fireEvent.click(screen.getByRole("menuitem", { name: /超收规则/ }));
    await screen.findByText("发布新版本");
    window.history.back();
    await screen.findByRole("heading", { name: "交货批次" });
    expect(window.location.pathname).toBe("/batches");
    window.history.forward();
    await waitFor(() => expect(screen.getByText("发布新版本")).toBeVisible());
    expect(window.location.pathname).toBe("/overreceipt");
  });
  it("shows overreceipt rule management to operators", async () => {
    state.authenticatedUser = operatorUser;

    render(<App />);

    await screen.findByRole("heading", { name: "交货批次" });
    expect(screen.getByRole("menuitem", { name: /超收规则/ })).toBeInTheDocument();
    expect(screen.queryByText("管理员维护")).not.toBeInTheDocument();
  });

  it("keeps the standard account header appearance in the batch workspace", async () => {
    state.authenticatedUser = adminUser;

    render(<App />);

    await screen.findByText("交货批次", { selector: "h2" });
    const listHeader = screen.getByLabelText("当前用户").closest(".app-header") as HTMLElement;
    const listStyle = getComputedStyle(listHeader);
    const listAppearance = {
      position: listStyle.position,
      height: listStyle.height,
      backgroundColor: listStyle.backgroundColor,
      borderBottomWidth: listStyle.borderBottomWidth,
      borderBottomStyle: listStyle.borderBottomStyle,
      paddingLeft: listStyle.paddingLeft,
      paddingRight: listStyle.paddingRight
    };

    fireEvent.click(await screen.findByLabelText("打开 路由测试批次"));
    await screen.findByText("路由测试批次", { selector: "h2" });
    const account = screen.getByLabelText("当前用户");
    const header = account.closest(".app-header") as HTMLElement;
    const detailStyle = getComputedStyle(header);

    expect(document.querySelector(".batch-focus-layout")).toBeInTheDocument();
    expect({
      position: detailStyle.position,
      height: detailStyle.height,
      backgroundColor: detailStyle.backgroundColor,
      borderBottomWidth: detailStyle.borderBottomWidth,
      borderBottomStyle: detailStyle.borderBottomStyle,
      paddingLeft: detailStyle.paddingLeft,
      paddingRight: detailStyle.paddingRight
    }).toEqual(listAppearance);
    expect(within(account).getByText("admin")).toBeVisible();
    expect(within(account).getByText("管理员")).toBeVisible();
  });

  it("keeps loaded batch actions stable while returning from another workspace", async () => {
    state.authenticatedUser = adminUser;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/auth/me")) {
          return new Response(JSON.stringify(adminUser), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.includes("/api/batches?")) {
          return new Response(JSON.stringify({ items: [routeBatch], total: 1, empty_draft_count: 0 }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/input-versions")) {
          return new Response(JSON.stringify(readyInputVersions), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/purchase-sync")) {
          return new Response(JSON.stringify({ configured: true, job: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (
          url.endsWith("/api/overreceipt-rule-versions") ||
          url.endsWith("/api/self-operated-overreceipt-rule-versions")
        ) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        throw new Error("Unexpected request: " + url);
      })
    );

    render(<App />);
    const initialButton = await screen.findByRole("button", { name: /新建批次/ });
    expect(initialButton).toBeEnabled();
    expect(await screen.findByRole("button", { name: /同步采购数据/ })).toBeEnabled();

    fireEvent.click(screen.getByRole("menuitem", { name: /超收规则/ }));
    await screen.findByText("发布新版本");
    fireEvent.click(screen.getByRole("menuitem", { name: /交货批次/ }));

    const returnedButton = screen.getByRole("button", { name: /新建批次/ });
    expect(returnedButton).toBe(initialButton);
    expect(returnedButton).toBeEnabled();
  }, 15000);

  it("returns to the top when switching workspaces", async () => {
    state.authenticatedUser = operatorUser;
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

    render(<App />);
    await screen.findByRole("heading", { name: "交货批次" });
    fireEvent.click(screen.getByRole("menuitem", { name: /超收规则/ }));
    await screen.findByText("发布新版本");

    expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "auto" });
  });

  it("restores a batch detail from its URL and returns to the list URL", async () => {
    state.authenticatedUser = adminUser;
    window.history.replaceState({}, "", "/batches/7");

    render(<App />);

    await screen.findByRole("heading", { name: "路由测试批次" });
    expect(window.location.pathname).toBe("/batches/7");

    fireEvent.click(screen.getByRole("button", { name: /返回批次列表/ }));

    await screen.findByRole("heading", { name: "交货批次" });
    expect(window.location.pathname).toBe("/batches");
  });

  it("updates the workspace when browser history emits popstate", async () => {
    state.authenticatedUser = adminUser;
    window.history.replaceState({}, "", "/batches");

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "路由测试批次" }));

    await screen.findByRole("heading", { name: "路由测试批次" });
    expect(window.location.pathname).toBe("/batches/7");

    window.history.replaceState({}, "", "/batches");
    window.dispatchEvent(new PopStateEvent("popstate"));

    await screen.findByRole("heading", { name: "交货批次" });
    expect(window.location.pathname).toBe("/batches");
  }, 10000);
});
