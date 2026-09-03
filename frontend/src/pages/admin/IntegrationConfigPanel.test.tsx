import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationConfigPanel } from "./IntegrationConfigPanel";

const jsonResponse = (payload: unknown, status = 200) => new Response(
  JSON.stringify(payload),
  {
    status,
    headers: { "Content-Type": "application/json" }
  }
);

describe("IntegrationConfigPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("does not show an unconfigured state before configuration is loaded", async () => {
    let resolveConfig!: (response: Response) => void;
    vi.mocked(fetch).mockReturnValueOnce(new Promise<Response>((resolve) => {
      resolveConfig = resolve;
    }));

    render(<IntegrationConfigPanel />);

    expect(screen.getByLabelText("正在读取接口配置")).toBeInTheDocument();
    expect(screen.queryByText("尚未配置")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "测试并保存" })).not.toBeInTheDocument();

    await act(async () => {
      resolveConfig(jsonResponse({
        configured: true,
        base_url: "https://open.gerpgo.com",
        app_id_hint: "ap***01",
        has_app_id: true,
        has_app_key: true,
        source: "environment"
      }));
      await Promise.resolve();
    });

    expect(await screen.findByText("配置可用")).toBeInTheDocument();
  });
  it("shows masked environment configuration without exposing the key", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      configured: true,
      base_url: "https://open.gerpgo.com",
      app_id_hint: "ap***01",
      has_app_id: true,
      has_app_key: true,
      source: "environment"
    }));

    render(<IntegrationConfigPanel />);

    expect(await screen.findByText("配置可用")).toBeInTheDocument();
    expect(
      screen.getByText("使用服务环境配置；保存后改用管理员配置。")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("complementary", { name: "连接概览" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "连接参数" })
    ).toBeInTheDocument();
    expect(screen.getByText("服务环境")).toBeInTheDocument();
    expect(screen.getByText(/当前：ap\*\*\*01/)).toBeInTheDocument();
    expect(screen.getByText("密钥已保存；留空则不修改")).toBeInTheDocument();
    expect(screen.queryByText(/secret/i)).not.toBeInTheDocument();
  });

  it("tests and saves a new configuration", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({
        configured: false,
        base_url: "https://open.gerpgo.com",
        app_id_hint: "",
        has_app_id: false,
        has_app_key: false,
        source: "environment"
      }))
      .mockResolvedValueOnce(jsonResponse({
        configured: true,
        base_url: "https://open.gerpgo.com",
        app_id_hint: "ap***01",
        has_app_id: true,
        has_app_key: true,
        source: "managed"
      }));

    render(<IntegrationConfigPanel />);

    expect(await screen.findByText("尚未配置")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("App ID"), {
      target: { value: "app-001" }
    });
    fireEvent.change(screen.getByLabelText("App Key"), {
      target: { value: "secret-key" }
    });
    fireEvent.click(screen.getByRole("button", { name: "测试并保存" }));

    expect(
      await screen.findByText("连接验证通过，配置已保存")
    ).toBeInTheDocument();
    expect(screen.getByText("使用管理员配置。")).toBeInTheDocument();

    const saveCall = vi.mocked(fetch).mock.calls.find(
      ([input, init]) => (
        String(input).endsWith("/api/admin/integrations/gerpgo")
        && init?.method === "PUT"
      )
    );
    expect(saveCall).toBeDefined();
    expect(JSON.parse(String(saveCall?.[1]?.body))).toEqual({
      base_url: "https://open.gerpgo.com",
      app_id: "app-001",
      app_key: "secret-key"
    });
    await waitFor(() => {
      expect(screen.getByLabelText(/App ID/)).toHaveValue("");
      expect(screen.getByLabelText(/App Key/)).toHaveValue("");
    });
  });

  it("keeps the form available when connection validation fails", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({
        configured: false,
        base_url: "https://open.gerpgo.com",
        app_id_hint: "",
        has_app_id: false,
        has_app_key: false,
        source: "environment"
      }))
      .mockResolvedValueOnce(jsonResponse(
        { detail: "积加连接验证失败：凭证无效" },
        400
      ));

    render(<IntegrationConfigPanel />);
    await screen.findByText("尚未配置");

    fireEvent.change(screen.getByLabelText("App ID"), {
      target: { value: "wrong-app" }
    });
    fireEvent.change(screen.getByLabelText("App Key"), {
      target: { value: "wrong-key" }
    });
    fireEvent.click(screen.getByRole("button", { name: "测试并保存" }));

    expect(await screen.findByText("操作失败")).toBeInTheDocument();
    expect(screen.getByText("积加连接验证失败：凭证无效")).toBeInTheDocument();
    expect(screen.getByLabelText("App ID")).toHaveValue("wrong-app");
    expect(screen.getByLabelText("App Key")).toHaveValue("wrong-key");
  });
});
