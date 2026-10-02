import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationConfigPanel } from "./IntegrationConfigPanel";
import { StrictMode } from "react";
import { api, AUTH_EXPIRED_EVENT } from "../../api";

const jsonResponse = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });

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
    vi.mocked(fetch).mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        resolveConfig = resolve;
      })
    );

    render(<IntegrationConfigPanel />);

    expect(screen.getByLabelText("正在读取接口配置")).toBeInTheDocument();
    expect(screen.queryByText("尚未配置")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "测试并保存" })).not.toBeInTheDocument();

    await act(async () => {
      resolveConfig(
        jsonResponse({
          configured: true,
          base_url: "https://open.gerpgo.com/api/open",
          app_id_hint: "ap***01",
          has_app_id: true,
          has_app_key: true,
          source: "environment"
        })
      );
      await Promise.resolve();
    });

    expect(await screen.findByText("配置可用")).toBeInTheDocument();
  });
  it("shows masked environment configuration without exposing the key", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        configured: true,
        base_url: "https://open.gerpgo.com/api/open",
        app_id_hint: "ap***01",
        has_app_id: true,
        has_app_key: true,
        source: "environment"
      })
    );

    render(<IntegrationConfigPanel />);

    expect(await screen.findByText("配置可用")).toBeInTheDocument();
    expect(screen.getByText("使用服务环境配置；保存后改用管理员配置。")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "连接概览" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "连接参数" })).toBeInTheDocument();
    expect(screen.getByText("服务环境")).toBeInTheDocument();
    expect(screen.getByText(/当前：ap\*\*\*01/)).toBeInTheDocument();
    expect(screen.getByText("密钥已保存；留空则不修改")).toBeInTheDocument();
    expect(screen.queryByText(/secret/i)).not.toBeInTheDocument();
  });

  it("tests and saves a new configuration", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          configured: false,
          base_url: "https://open.gerpgo.com/api/open",
          app_id_hint: "",
          has_app_id: false,
          has_app_key: false,
          source: "environment"
        })
      )
      .mockResolvedValueOnce(
        jsonResponse({
          configured: true,
          base_url: "https://open.gerpgo.com/api/open",
          app_id_hint: "ap***01",
          has_app_id: true,
          has_app_key: true,
          source: "managed"
        })
      );

    render(<IntegrationConfigPanel />);

    expect(await screen.findByText("尚未配置")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("App ID"), {
      target: { value: "app-001" }
    });
    fireEvent.change(screen.getByLabelText("App Key"), {
      target: { value: "secret-key" }
    });
    fireEvent.click(screen.getByRole("button", { name: "测试并保存" }));

    expect(await screen.findByText("连接验证通过，配置已保存")).toBeInTheDocument();
    expect(screen.getByText("使用管理员配置。")).toBeInTheDocument();

    const saveCall = vi
      .mocked(fetch)
      .mock.calls.find(
        ([input, init]) => String(input).endsWith("/api/admin/integrations/gerpgo") && init?.method === "PUT"
      );
    expect(saveCall).toBeDefined();
    expect(JSON.parse(String(saveCall?.[1]?.body))).toEqual({
      base_url: "https://open.gerpgo.com/api/open",
      app_id: "app-001",
      app_key: "secret-key"
    });
    await waitFor(() => {
      expect(screen.getByLabelText(/App ID/)).toHaveValue("");
      expect(screen.getByLabelText(/App Key/)).toHaveValue("");
    });
  });

  it("reports an unknown state after a read failure and preserves edits on retry", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: "合成读取失败" }, 500))
      .mockResolvedValueOnce(
        jsonResponse({ configured: true, base_url: "https://server.example/api", source: "managed" })
      );
    render(<IntegrationConfigPanel />);
    await screen.findByText("合成读取失败");
    expect(screen.queryByText("尚未配置")).not.toBeInTheDocument();
    expect(screen.queryByText("服务环境")).not.toBeInTheDocument();
    expect(screen.getByText("状态未知")).toBeInTheDocument();
    for (const [label, value] of [
      ["API 地址", "https://draft.example/api"],
      ["App ID", "draft-id"],
      ["App Key", "draft-key"]
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByText("重新读取", { selector: "button > span" }));
    await screen.findByText("配置可用");
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://draft.example/api");
    expect(screen.getByLabelText(/App ID/)).toHaveValue("draft-id");
    expect(screen.getByLabelText(/App Key/)).toHaveValue("draft-key");
  });

  it.each(["read", "save"])("ignores older and unmounted configuration responses during %s", async (operation) => {
    const responses: ((response: Response) => void)[] = [];
    vi.mocked(fetch).mockImplementation(() => new Promise((resolve) => responses.push(resolve)));
    const view = render(
      <StrictMode>
        <IntegrationConfigPanel />
      </StrictMode>
    );
    expect(responses).toHaveLength(2);
    await act(async () =>
      responses[1](
        jsonResponse({
          configured: true,
          base_url: "https://new.example/api",
          has_app_id: true,
          has_app_key: true,
          source: "managed"
        })
      )
    );
    await act(async () =>
      responses[0](jsonResponse({ configured: false, base_url: "https://old.example/api", source: "environment" }))
    );
    expect(screen.getByText("配置可用")).toBeInTheDocument();
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://new.example/api");
    fireEvent.click(screen.getByText(operation === "read" ? "重新读取" : "测试并保存", { selector: "button > span" }));
    await waitFor(() => expect(responses).toHaveLength(3));
    view.unmount();
    await act(async () => responses[2](jsonResponse({ detail: "迟到的读取错误" }, 500)));
    expect(screen.queryByText("迟到的读取错误")).not.toBeInTheDocument();
  });

  it("uses saved server metadata and preserves new edits when rereading", async () => {
    const config = {
      configured: true,
      base_url: "https://server.example/api",
      has_app_id: true,
      has_app_key: true,
      source: "managed"
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(config))
      .mockResolvedValueOnce(jsonResponse({ ...config, base_url: "https://normalized.example/api" }))
      .mockResolvedValueOnce(jsonResponse(config));
    render(<IntegrationConfigPanel />);
    await screen.findByText("配置可用");
    fireEvent.change(screen.getByLabelText(/App Key/), { target: { value: "synthetic-key" } });
    fireEvent.click(screen.getByText("测试并保存", { selector: "button > span" }));
    await screen.findByText("连接验证通过，配置已保存");
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://normalized.example/api");
    expect(screen.getByLabelText(/App Key/)).toHaveValue("");
    fireEvent.change(screen.getByLabelText(/App Key/), { target: { value: "unsaved-key" } });
    fireEvent.click(screen.getByText("重新读取", { selector: "button > span" }));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.getByText("测试并保存", { selector: "button > span" }).closest("button")).toBeEnabled()
    );
    expect(screen.getByLabelText(/App Key/)).toHaveValue("unsaved-key");
    expect(screen.getByLabelText("API 地址")).toHaveValue("https://normalized.example/api");
    expect(screen.queryByText("连接验证通过，配置已保存")).not.toBeInTheDocument();
  });

  it.each(["read", "save"])("leaves %s unauthorized feedback to authentication", async (operation) => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ id: 1 }));
    await api("/api/auth/me");
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    vi.mocked(fetch).mockResolvedValueOnce(
      operation === "read"
        ? jsonResponse({ detail: "合成未登录" }, 401)
        : jsonResponse({
            configured: true,
            base_url: "https://server.example/api",
            has_app_id: true,
            has_app_key: true,
            source: "managed"
          })
    );
    try {
      render(<IntegrationConfigPanel />);
      if (operation === "save") {
        await screen.findByText("配置可用");
        vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ detail: "合成未登录" }, 401));
        fireEvent.click(screen.getByText("测试并保存", { selector: "button > span" }));
      }
      await waitFor(() => expect(expired).toHaveBeenCalledOnce());
      await waitFor(() =>
        expect(screen.getByText("测试并保存", { selector: "button > span" }).closest("button")).toBeEnabled()
      );
      expect(screen.queryByText("合成未登录")).not.toBeInTheDocument();
      expect(screen.queryByText("连接验证通过，配置已保存")).not.toBeInTheDocument();
    } finally {
      window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    }
  });

  it("keeps the form available when connection validation fails", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        jsonResponse({
          configured: false,
          base_url: "https://open.gerpgo.com/api/open",
          app_id_hint: "",
          has_app_id: false,
          has_app_key: false,
          source: "environment"
        })
      )
      .mockResolvedValueOnce(jsonResponse({ detail: "积加连接验证失败：凭证无效" }, 400));

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
