import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { message } from "antd";
import { describe, expect, it, vi } from "vitest";
import OverreceiptRulesPage from "../OverreceiptRulesPage";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import { render, setupRuleTests, selfOperatedRule, rulesTestState } from "./ruleTestSupport";

setupRuleTests();

describe("OverreceiptRulesPage", () => {
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

  it("keeps a failed publication confirmation open and allows retry", async () => {
    rulesTestState.failPublishOnce = true;
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
  it("发布自营仓规则后打开交货表单仍保留独立默认额度", async () => {
    render(<OverreceiptRulesPage />);
    await screen.findByText(selfOperatedRule.name);
    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    fireEvent.change(screen.getByLabelText("规则版本名称"), { target: { value: "表单切换测试" } });
    fireEvent.click(screen.getByRole("button", { name: /确\s*认/ }));
    fireEvent.click(await screen.findByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "发布自营仓新版本" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    expect(screen.getByRole("spinbutton", { name: "短尾允许超收" })).toHaveValue("50");
    expect(screen.getByRole("spinbutton", { name: "中尾允许超收" })).toHaveValue("20");
    expect(screen.getByRole("spinbutton", { name: "长尾允许超收" })).toHaveValue("10");
  });
});
