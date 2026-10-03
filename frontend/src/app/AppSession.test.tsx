import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ConfigProvider, message } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupAppTests, submitLogin, adminUser } from "./appTestSupport";
import { api } from "../api";
import App from "../App";

describe("AppSession", () => {
  const state = setupAppTests();
  it("returns to login even when the logout request fails", async () => {
    state.authenticatedUser = adminUser;
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("/api/auth/logout")
          ? Promise.reject(new TypeError("合成网络故障"))
          : originalFetch(input, init)
      )
    );
    render(<App />);
    await screen.findByRole("heading", { name: "交货批次" });
    localStorage.setItem("delivery-note-user", "旧用户缓存");
    sessionStorage.setItem("delivery-note-token", "legacy-token");
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));
    await screen.findByRole("heading", { name: "欢迎回来" });
    expect(localStorage.getItem("delivery-note-user")).toBeNull();
    expect(sessionStorage.getItem("delivery-note-token")).toBeNull();
    expect(screen.queryByRole("group", { name: "当前用户" })).not.toBeInTheDocument();
  });
  it("shows a structured account area and keeps logout working", async () => {
    state.authenticatedUser = adminUser;

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
    expect(fetch).toHaveBeenCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST" }));
  });

  it("returns to login when a cookie session expires", async () => {
    const staticWarning = vi.spyOn(message, "warning");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/auth/me")) {
          return new Response(JSON.stringify(adminUser), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        return new Response(JSON.stringify({ detail: "未登录" }), {
          status: 401,
          headers: { "Content-Type": "application/json" }
        });
      })
    );

    render(<App />);

    await screen.findByRole("button", { name: /登\s*录/ });
    expect(await screen.findByText("登录已过期，请重新登录")).toBeInTheDocument();
    expect(staticWarning).not.toHaveBeenCalled();
    expect(localStorage.getItem("delivery-note-token")).toBeNull();
    expect(localStorage.getItem("delivery-note-user")).toBeNull();
    expect(fetch).toHaveBeenCalled();
  });

  it("reports concurrent unauthorized requests once and resets after logging in again", async () => {
    state.authenticatedUser = adminUser;
    const staticWarning = vi.spyOn(message, "warning");
    const authenticatedFetch = fetch;
    let expired = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        expired
          ? Promise.resolve(new Response(JSON.stringify({ detail: "未登录" }), { status: 401 }))
          : authenticatedFetch(input, init)
      )
    );
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <App />
      </ConfigProvider>
    );
    await screen.findByRole("heading", { name: "交货批次" });

    for (let episode = 0; episode < 2; episode += 1) {
      expired = true;
      await act(async () => {
        const results = await Promise.allSettled([api("/api/input-versions"), api("/api/purchase-sync")]);
        expect(results.every((result) => result.status === "rejected")).toBe(true);
      });
      await screen.findByRole("heading", { name: "欢迎回来" });
      await screen.findByText("登录已过期，请重新登录");
      expect(screen.getAllByText("登录已过期，请重新登录")).toHaveLength(1);
      expect(staticWarning).not.toHaveBeenCalled();
      if (episode === 1) break;

      expired = false;
      submitLogin("admin", "admin-pass");
      await screen.findByRole("heading", { name: "交货批次" });
      await waitFor(() => expect(screen.queryByText("登录已过期，请重新登录")).not.toBeInTheDocument(), {
        timeout: 5000
      });
    }
  }, 15000);
});
