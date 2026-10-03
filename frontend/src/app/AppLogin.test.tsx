import { render, screen, waitFor } from "@testing-library/react";
import { message } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupAppTests, submitLogin } from "./appTestSupport";
import App from "../App";

describe("AppLogin", () => {
  setupAppTests();
  it("shows login without an expiration warning on an anonymous visit", async () => {
    const staticWarning = vi.spyOn(message, "warning");
    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });
    expect(screen.queryByText("登录已过期，请重新登录")).not.toBeInTheDocument();
    expect(staticWarning).not.toHaveBeenCalled();
  });

  it("logs in and opens the batch workspace", async () => {
    localStorage.setItem("delivery-note-token", "legacy-token");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "欢迎回来" })).toBeInTheDocument();
    expect(screen.getByText("SEEKWAY")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /让每一份交货数据，\s*清晰抵达下一站/ })).toBeInTheDocument();
    expect(screen.getByText("请使用系统账号登录")).toBeInTheDocument();
    expect(screen.getByText("DeliveryNote · 内部供应链单据处理系统")).toBeInTheDocument();

    submitLogin("admin", "admin-pass");

    await screen.findByRole("heading", { name: "交货批次" });
    expect(screen.getByText("单据处理")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /交货批次/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /超收规则/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /管理员维护/ })).toBeInTheDocument();
    expect(localStorage.getItem("delivery-note-token")).toBeNull();
    expect(sessionStorage.getItem("delivery-note-token")).toBeNull();
    await waitFor(() => {
      const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
      expect(requestedUrls).toEqual(
        expect.arrayContaining([
          "/api/auth/login",
          "/api/batches?workflow=delivery&offset=0&limit=12",
          "/api/input-versions",
          "/api/purchase-sync",
          "/api/overreceipt-rule-versions"
        ])
      );
      for (const [, init] of vi.mocked(fetch).mock.calls) {
        expect(init).toEqual(expect.objectContaining({ credentials: "include" }));
        expect(new Headers(init?.headers).has("Authorization")).toBe(false);
      }
    });
  });

  it("shows only the credential error when login is rejected", async () => {
    const staticError = vi.spyOn(message, "error");
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(
        JSON.stringify({
          detail: url.endsWith("/api/auth/login") ? "用户名或密码错误" : "未登录"
        }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    });

    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });

    submitLogin("admin", "wrong-password");

    expect(await screen.findByText("用户名或密码错误")).toBeInTheDocument();
    expect(screen.queryByText("登录已过期，请重新登录")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("请输入用户名")).toHaveValue("admin");
    expect(screen.getByPlaceholderText("请输入密码")).toHaveValue("wrong-password");
    await waitFor(() => expect(screen.getByRole("button", { name: /登\s*录/ })).not.toHaveClass("ant-btn-loading"));
    expect(staticError).not.toHaveBeenCalled();
  });
});
