import type { ReactElement } from "react";
import { act, fireEvent, render as renderComponent, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp, message } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OverreceiptRulesPage from "./OverreceiptRulesPage";
import { api, AUTH_EXPIRED_EVENT } from "../api";

const render = (ui: ReactElement) => renderComponent(ui, { wrapper: AntApp });

const firstRule = {
  id: 1,
  name: "2026-07 短尾放宽",
  short_tail_limit: 50,
  medium_tail_limit: 20,
  long_tail_limit: 10,
  allowed_warehouses: ["水鞋-广州仓"],
  active: true,
  created_by: 2,
  created_at: "2026-07-22T08:00:00"
};

const previousRule = {
  ...firstRule,
  id: 0,
  name: "2026-06 基线规则",
  allowed_warehouses: [],
  active: false,
  created_at: "2026-06-22T08:00:00"
};

const selfOperatedRule = {
  id: 11,
  name: "Windows验收-每键超收5件",
  allowance: 5,
  active: true,
  created_by: 1,
  created_at: "2026-08-24T04:08:41Z"
};

const previousSelfOperatedRule = {
  ...selfOperatedRule,
  id: 10,
  name: "自营仓基线规则",
  allowance: 3,
  active: false,
  created_at: "2026-08-20T04:08:41Z"
};

const jsonResponse = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });

let failPublishOnce = false;
let deliveryRuleRows = [firstRule, previousRule];
let selfOperatedRuleRows = [selfOperatedRule, previousSelfOperatedRule];

describe("OverreceiptRulesPage", () => {
  beforeEach(() => {
    failPublishOnce = false;
    deliveryRuleRows = [firstRule, previousRule];
    selfOperatedRuleRows = [selfOperatedRule, previousSelfOperatedRule];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/api/auth/me")) return jsonResponse({ id: 1 });
        if (url.endsWith("/api/overreceipt-rule-versions/warehouses")) {
          return jsonResponse(["供应商成品本地仓", "水鞋-广州仓"]);
        }
        if (url.endsWith("/api/overreceipt-rule-versions") && method === "GET") {
          return jsonResponse(deliveryRuleRows);
        }
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions") && method === "GET") {
          return jsonResponse(selfOperatedRuleRows);
        }
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions") && method === "POST") {
          return jsonResponse({ ...selfOperatedRule, id: 12, name: "2026-09 自营仓规则" }, 201);
        }
        const selfOperatedRenameMatch = url.match(/\/api\/self-operated-overreceipt-rule-versions\/(\d+)\/name$/);
        if (selfOperatedRenameMatch && method === "PUT") {
          const id = Number(selfOperatedRenameMatch[1]);
          const { name } = JSON.parse(String(init?.body));
          selfOperatedRuleRows = selfOperatedRuleRows.map((rule) => (rule.id === id ? { ...rule, name } : rule));
          return jsonResponse(selfOperatedRuleRows.find((rule) => rule.id === id));
        }
        if (url.endsWith("/api/overreceipt-rule-versions") && method === "POST") {
          if (failPublishOnce) {
            failPublishOnce = false;
            return jsonResponse({ detail: "发布服务暂时不可用" }, 500);
          }
          return jsonResponse({ ...firstRule, id: 2, name: "2026-08 新规则" }, 201);
        }
        const deliveryRenameMatch = url.match(/\/api\/overreceipt-rule-versions\/(\d+)\/name$/);
        if (deliveryRenameMatch && method === "PUT") {
          const id = Number(deliveryRenameMatch[1]);
          const { name } = JSON.parse(String(init?.body));
          deliveryRuleRows = deliveryRuleRows.map((rule) => (rule.id === id ? { ...rule, name } : rule));
          return jsonResponse(deliveryRuleRows.find((rule) => rule.id === id));
        }
        throw new Error(`Unexpected request: ${method} ${url}`);
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows self-operated rules by default and publishes from the drawer", async () => {
    render(<OverreceiptRulesPage />);

    expect(await screen.findAllByText("Windows验收-每键超收5件")).toHaveLength(1);
    expect(screen.getAllByText("+5 件").length).toBeGreaterThan(0);
    const historyTable = screen.getByRole("table", { name: "自营仓超收规则历史版本" });
    expect(within(historyTable).queryByText("Windows验收-每键超收5件")).not.toBeInTheDocument();
    expect(within(historyTable).getByText("自营仓基线规则")).toBeInTheDocument();
    expect(screen.getByText("1 个历史版本")).toBeInTheDocument();
    expect(screen.getByText("仅用于新批次；已有批次仍使用原版本。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    expect(await screen.findByText("发布自营仓新版本")).toBeInTheDocument();
    expect(screen.getByText("规则内超收挂到最后一个 PO 单")).toBeVisible();
    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-09 自营仓规则" }
    });
    expect(screen.getByRole("spinbutton", { name: "每个匹配键允许超收" })).toHaveValue("5");
    const drawerConfirmButton = screen.getByRole("button", { name: /确\s*认/ });
    expect(drawerConfirmButton).toHaveAttribute("type", "submit");
    expect(drawerConfirmButton).toHaveAttribute("form", "self-operated-overreceipt-form");
    fireEvent.click(drawerConfirmButton);

    const confirmTitle = await screen.findByText("确认发布自营仓超收规则？", { selector: ".ant-modal-confirm-title" });
    const dialog = confirmTitle.closest<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(within(dialog!).getByText("2026-09 自营仓规则")).toBeInTheDocument();
    fireEvent.click(within(dialog!).getByRole("button", { name: "确认发布" }));

    await waitFor(() => {
      const post = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) =>
            String(input).endsWith("/api/self-operated-overreceipt-rule-versions") && init?.method === "POST"
        );
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        name: "2026-09 自营仓规则",
        allowance: 5
      });
    });
  });

  it("shows the active immutable version and publishes an exact warehouse whitelist", async () => {
    render(<OverreceiptRulesPage />);

    await screen.findAllByText("Windows验收-每键超收5件");
    fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    expect(screen.getAllByText("2026-07 短尾放宽").length).toBeGreaterThan(0);
    expect(screen.getAllByText("短尾 +50").length).toBeGreaterThan(0);
    expect(screen.getAllByText("中尾 +20").length).toBeGreaterThan(0);
    expect(screen.getAllByText("长尾 +10").length).toBeGreaterThan(0);
    expect(screen.queryByText("供应链成品仓")).not.toBeInTheDocument();
    const historyTable = screen.getByRole("table", { name: "超收规则不可变版本" });
    expect(within(historyTable).queryByText("2026-07 短尾放宽")).not.toBeInTheDocument();
    expect(within(historyTable).getByText("2026-06 基线规则")).toBeInTheDocument();
    expect(screen.getAllByText("未开放任何仓库").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "重新启用 2026-06 基线规则" })).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/overreceipt-rule-versions/warehouses"))
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    expect(screen.getByText(/供应商成品本地仓/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-08 新规则" }
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "允许超收仓库" }));
    fireEvent.click(await screen.findByText("水鞋-广州仓", { selector: ".ant-select-item-option-content" }));
    expect(
      vi
        .mocked(fetch)
        .mock.calls.filter(([input]) => String(input).endsWith("/api/overreceipt-rule-versions/warehouses"))
    ).toHaveLength(1);
    const drawerConfirmButton = screen.getByRole("button", { name: /确\s*认/ });
    expect(drawerConfirmButton).toHaveAttribute("type", "submit");
    expect(drawerConfirmButton).toHaveAttribute("form", "delivery-overreceipt-form");
    fireEvent.click(drawerConfirmButton);

    const confirmTitle = await screen.findByText("确认发布不可变版本？", { selector: ".ant-modal-confirm-title" });
    const dialog = confirmTitle.closest<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(within(dialog!).getByText("2026-08 新规则")).toBeInTheDocument();
    expect(within(dialog!).getByText("短尾 +50 件")).toBeInTheDocument();
    expect(within(dialog!).getByText("中尾 +20 件")).toBeInTheDocument();
    expect(within(dialog!).getByText("长尾 +10 件")).toBeInTheDocument();
    expect(within(dialog!).getByText("水鞋-广州仓")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    fireEvent.click(within(dialog!).getByRole("button", { name: "确认发布" }));

    await waitFor(() => {
      const post = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({
        name: "2026-08 新规则",
        short_tail_limit: 50,
        medium_tail_limit: 20,
        long_tail_limit: 10,
        allowed_warehouses: ["水鞋-广州仓"]
      });
    });
  }, 10_000);

  it("keeps the current version out of an empty history state", async () => {
    deliveryRuleRows = [firstRule];
    selfOperatedRuleRows = [selfOperatedRule];

    render(<OverreceiptRulesPage />);

    expect(await screen.findAllByText("Windows验收-每键超收5件")).toHaveLength(1);
    expect(screen.getByText("0 个历史版本")).toBeInTheDocument();
    expect(screen.getByText("暂无历史版本")).toBeInTheDocument();
    expect(screen.getByText("发布新版本后，原版本会移到这里。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    expect(screen.getAllByText("2026-07 短尾放宽")).toHaveLength(1);
    expect(screen.getByText("0 个历史版本")).toBeInTheDocument();
  });

  it("renames current and historical versions without editing rule parameters", async () => {
    render(<OverreceiptRulesPage />);

    await screen.findAllByText("Windows验收-每键超收5件");
    fireEvent.click(screen.getByRole("button", { name: "重命名 自营仓基线规则" }));
    const selfOperatedDialog = await screen.findByRole("dialog", { name: "修改版本名称" });
    expect(within(selfOperatedDialog).getByLabelText("版本名称")).toHaveValue("自营仓基线规则");
    expect(within(selfOperatedDialog).getByText("只修改名称，不影响规则参数或历史批次")).toBeInTheDocument();
    fireEvent.change(within(selfOperatedDialog).getByLabelText("版本名称"), {
      target: { value: "自营仓历史规则新名称" }
    });
    fireEvent.click(within(selfOperatedDialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      const rename = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) =>
            String(input).endsWith("/api/self-operated-overreceipt-rule-versions/10/name") && init?.method === "PUT"
        );
      expect(rename).toBeDefined();
      expect(JSON.parse(String(rename?.[1]?.body))).toEqual({
        name: "自营仓历史规则新名称"
      });
    });
    expect(await screen.findByText("自营仓历史规则新名称")).toBeInTheDocument();
    expect(screen.getAllByText("+3 件").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    fireEvent.click(screen.getByRole("button", { name: "重命名 2026-07 短尾放宽" }));
    const deliveryDialog = await screen.findByRole("dialog", { name: "修改版本名称" });
    fireEvent.change(within(deliveryDialog).getByLabelText("版本名称"), {
      target: { value: "交货当前规则新名称" }
    });
    fireEvent.click(within(deliveryDialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      const rename = vi
        .mocked(fetch)
        .mock.calls.find(
          ([input, init]) => String(input).endsWith("/api/overreceipt-rule-versions/1/name") && init?.method === "PUT"
        );
      expect(rename).toBeDefined();
      expect(JSON.parse(String(rename?.[1]?.body))).toEqual({
        name: "交货当前规则新名称"
      });
    });
    expect(await screen.findAllByText("交货当前规则新名称")).toHaveLength(1);
    expect(screen.getAllByText("短尾 +50").length).toBeGreaterThan(0);
  });

  it("keeps a failed publication confirmation open and allows retry", async () => {
    failPublishOnce = true;
    render(<OverreceiptRulesPage />);

    await screen.findAllByText("Windows验收-每键超收5件");
    fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-08 重试规则" }
    });
    fireEvent.click(screen.getByRole("button", { name: /确\s*认/ }));

    const ruleName = await screen.findByText("2026-08 重试规则");
    const dialog = ruleName.closest<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    const confirmButton = within(dialog!).getByRole("button", { name: "确认发布" });
    fireEvent.click(confirmButton);

    expect(await screen.findByText("发布服务暂时不可用")).toBeInTheDocument();
    expect(dialog).toBeInTheDocument();
    await waitFor(() => expect(confirmButton).toBeEnabled());

    fireEvent.click(confirmButton);
    await waitFor(() => {
      const posts = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
      expect(posts).toHaveLength(2);
    });
    await waitFor(() => expect(dialog).toHaveClass("ant-zoom-leave"));
  });

  it.each(["delivery", "self_operated"])("does not repeat a saved %s publication when refresh fails", async (scope) => {
    const originalFetch = fetch;
    let saved = false;
    let failRefresh = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") saved = true;
        if (saved && failRefresh && !init?.method) return jsonResponse({ detail: "读取暂不可用" }, 500);
        return originalFetch(input, init);
      })
    );
    const staticSuccess = vi.spyOn(message, "success");
    render(<OverreceiptRulesPage />);
    await screen.findByText(selfOperatedRule.name);
    if (scope === "delivery") fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    fireEvent.change(screen.getByLabelText("规则版本名称"), { target: { value: "规则<&>" } });
    fireEvent.click(screen.getByRole("button", { name: /确\s*认/ }));
    const confirm = await screen.findByRole("button", { name: "确认发布" });
    const dialog = confirm.closest('[role="dialog"]');
    fireEvent.click(confirm);
    expect(await screen.findByText(/变更已保存.*读取暂不可用/)).toBeInTheDocument();
    await waitFor(() => expect(dialog).toHaveClass("ant-zoom-leave"));
    expect(screen.queryByText(/已发布，将用于新批次/)).not.toBeInTheDocument();
    failRefresh = false;
    fireEvent.click(screen.getByRole("button", { name: /重\s*试/ }));
    await waitFor(() => expect(screen.queryByText("超收规则读取失败")).not.toBeInTheDocument());
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(staticSuccess).not.toHaveBeenCalled();
  });

  it("ignores an older read that arrives after a newer read", async () => {
    const originalFetch = fetch;
    let resolveOld!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveOld = resolve;
    });
    let reads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/api/self-operated-overreceipt-rule-versions")) {
          reads += 1;
          return reads === 1 ? pending : Promise.resolve(jsonResponse([{ ...selfOperatedRule, name: "最新规则" }]));
        }
        return originalFetch(input, init);
      })
    );
    const view = render(<OverreceiptRulesPage active />);
    view.rerender(<OverreceiptRulesPage active={false} />);
    expect(await screen.findByText("最新规则")).toBeInTheDocument();
    await act(async () => {
      resolveOld(jsonResponse([selfOperatedRule]));
    });
    expect(screen.queryByText(selfOperatedRule.name)).not.toBeInTheDocument();
  });

  it.each(
    ["delivery", "self_operated"].flatMap((scope) => [403, 409, 422, 500, 0, 401].map((status) => ({ scope, status })))
  )("handles $scope activation error $status without success feedback", async ({ scope, status }) => {
    await api("/api/auth/me");
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/activate")) {
          return status === 0
            ? Promise.reject(new Error("网络断开"))
            : Promise.resolve(jsonResponse({ detail: `启用失败 ${status}` }, status));
        }
        return originalFetch(input, init);
      })
    );
    render(<OverreceiptRulesPage />);
    await screen.findByText(selfOperatedRule.name);
    if (scope === "delivery") fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    const button = () =>
      screen.getByRole("button", {
        name: `重新启用 ${scope === "delivery" ? previousRule.name : previousSelfOperatedRule.name}`
      });
    fireEvent.click(button());
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/activate"))).toHaveLength(1)
    );
    if (status !== 401)
      expect(await screen.findByText(status === 0 ? "网络断开" : `启用失败 ${status}`)).toBeInTheDocument();
    await waitFor(() => expect(button()).not.toHaveClass("ant-btn-loading"));
    expect(screen.queryByText(/已重新启用/)).not.toBeInTheDocument();
    expect(screen.queryByText("启用失败 401")).not.toBeInTheDocument();
  });

  it.each(["initial", "after-write"])("leaves %s 401 feedback to authentication", async (phase) => {
    await api("/api/auth/me");
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    const originalFetch = fetch;
    let saved = phase === "initial";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") saved = true;
        if (saved && !init?.method) return jsonResponse({ detail: "未登录" }, 401);
        return originalFetch(input, init);
      })
    );
    try {
      render(<OverreceiptRulesPage />);
      if (phase === "after-write") {
        await screen.findByText(selfOperatedRule.name);
        fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
        fireEvent.change(screen.getByLabelText("规则版本名称"), { target: { value: "规则" } });
        fireEvent.click(screen.getByRole("button", { name: /确\s*认/ }));
        const confirm = await screen.findByRole("button", { name: "确认发布" });
        fireEvent.click(confirm);
        await waitFor(() => expect(confirm.closest('[role="dialog"]')).toHaveClass("ant-zoom-leave"));
      }
      await waitFor(() => expect(expired).toHaveBeenCalledTimes(1));
      expect(screen.queryByText("未登录")).not.toBeInTheDocument();
      expect(screen.queryByText("超收规则读取失败")).not.toBeInTheDocument();
      expect(screen.queryByText(/已发布，将用于新批次/)).not.toBeInTheDocument();
    } finally {
      window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    }
  });
});
