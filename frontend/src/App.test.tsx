import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import "./styles.css";

const routeBatch = {
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

const readyInputVersions = ["purchase", "product", "supplier", "position", "template"].map((kind, index) => ({
  id: index + 1,
  kind,
  name: `${kind}-v1`,
  original_name: `${kind}.xlsx`,
  active: true,
  created_by: 1,
  created_at: "2026-08-26T08:00:00"
}));
describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, "", "/");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/auth/login")) {
          return new Response(
            JSON.stringify({
              token: "token-1",
              user: { id: 1, username: "admin", role: "admin", active: true }
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (url.endsWith("/api/auth/logout")) {
          return new Response(null, { status: 204 });
        }
        if (url.endsWith("/api/batches/7/exceptions")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/batches/7")) {
          return new Response(JSON.stringify(routeBatch), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/batches")) {
          return new Response(JSON.stringify([routeBatch]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/input-versions")) {
          return new Response(JSON.stringify([]), {
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
        if (url.endsWith("/api/self-operated-inbound-sync")) {
          return new Response(JSON.stringify({ configured: true, job: null, active_version: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/overreceipt-rule-versions")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/overreceipt-rule-versions/warehouses")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/users") || url.endsWith("/api/audit-logs")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    document.querySelectorAll(".ant-message").forEach((node) => node.remove());
    vi.unstubAllGlobals();
  });

  it("logs in and opens the batch workspace", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "供应链单据处理" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "admin" }
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "admin-pass" }
    });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));

    await screen.findByRole("heading", { name: "交货批次" });
    expect(screen.getByText("单据处理")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /交货批次/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /超收规则/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /管理员维护/ })).toBeInTheDocument();
    expect(localStorage.getItem("delivery-note-token")).toBe("token-1");
    await waitFor(() => {
      const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
      expect(requestedUrls).toEqual(expect.arrayContaining([
        "/api/auth/login",
        "/api/batches",
        "/api/input-versions",
        "/api/purchase-sync",
        "/api/overreceipt-rule-versions"
      ]));
    });
  });

  it("shows overreceipt rule management to operators", async () => {
    localStorage.setItem("delivery-note-token", "operator-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 2,
      username: "operator",
      role: "operator",
      active: true
    }));

    render(<App />);

    await screen.findByRole("heading", { name: "交货批次" });
    expect(screen.getByRole("menuitem", { name: /超收规则/ })).toBeInTheDocument();
    expect(screen.queryByText("管理员维护")).not.toBeInTheDocument();
  });

  it("shows a structured account area and keeps logout working", async () => {
    localStorage.setItem("delivery-note-token", "admin-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));

    render(<App />);
    await screen.findByRole("heading", { name: "交货批次" });

    const account = screen.getByRole("group", { name: "当前用户" });
    expect(within(account).getByText("A")).toBeInTheDocument();
    expect(within(account).getByText("admin")).toBeInTheDocument();
    expect(within(account).getByText("管理员")).toBeInTheDocument();

    fireEvent.click(within(account).getByRole("button", { name: "退出登录" }));

    await screen.findByRole("button", { name: /登\s*录/ });
    expect(localStorage.getItem("delivery-note-token")).toBeNull();
    expect(localStorage.getItem("delivery-note-user")).toBeNull();
    expect(fetch).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("keeps the standard account header appearance in the batch workspace", async () => {
    localStorage.setItem("delivery-note-token", "admin-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));

    render(<App />);

    await screen.findByRole("heading", { name: "交货批次" });
    const listHeader = screen.getByRole("group", { name: "当前用户" }).closest(".app-header") as HTMLElement;
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

    fireEvent.click(
      await screen.findByRole("button", { name: "路由测试批次" })
    );
    await screen.findByRole("heading", { name: "路由测试批次" });
    const account = screen.getByRole("group", { name: "当前用户" });
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
    localStorage.setItem("delivery-note-token", "admin-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/batches")) {
          return new Response(JSON.stringify([routeBatch]), {
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
          url.endsWith("/api/overreceipt-rule-versions")
          || url.endsWith("/api/self-operated-overreceipt-rule-versions")
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
    localStorage.setItem("delivery-note-token", "operator-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 2,
      username: "operator",
      role: "operator",
      active: true
    }));
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

    render(<App />);
    await screen.findByRole("heading", { name: "交货批次" });
    fireEvent.click(screen.getByRole("menuitem", { name: /超收规则/ }));
    await screen.findByText("发布新版本");

    expect(scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "auto" });
  });

  it("returns to login when a stored session expires", async () => {
    localStorage.setItem("delivery-note-token", "expired-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "未登录" }),
      { status: 401, headers: { "Content-Type": "application/json" } }
    )));

    render(<App />);

    await screen.findByRole("button", { name: /登\s*录/ });
    expect(localStorage.getItem("delivery-note-token")).toBeNull();
    expect(localStorage.getItem("delivery-note-user")).toBeNull();
    expect(fetch).toHaveBeenCalled();
  });

  it("restores a batch detail from its URL and returns to the list URL", async () => {
    localStorage.setItem("delivery-note-token", "admin-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));
    window.history.replaceState({}, "", "/batches/7");

    render(<App />);

    await screen.findByRole("heading", { name: "路由测试批次" });
    expect(window.location.pathname).toBe("/batches/7");

    fireEvent.click(screen.getByRole("button", { name: /返回批次列表/ }));

    await screen.findByRole("heading", { name: "交货批次" });
    expect(window.location.pathname).toBe("/batches");
  });

  it("updates the workspace when browser history emits popstate", async () => {
    localStorage.setItem("delivery-note-token", "admin-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));
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
