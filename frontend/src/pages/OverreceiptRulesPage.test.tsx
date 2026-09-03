import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OverreceiptRulesPage from "./OverreceiptRulesPage";

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

const jsonResponse = (payload: unknown, status = 200) => new Response(
  JSON.stringify(payload),
  { status, headers: { "Content-Type": "application/json" } }
);

let failPublishOnce = false;
let deliveryRuleRows = [firstRule, previousRule];
let selfOperatedRuleRows = [selfOperatedRule, previousSelfOperatedRule];

describe("OverreceiptRulesPage", () => {
  beforeEach(() => {
    failPublishOnce = false;
    deliveryRuleRows = [firstRule, previousRule];
    selfOperatedRuleRows = [selfOperatedRule, previousSelfOperatedRule];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
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
      const selfOperatedRenameMatch = url.match(
        /\/api\/self-operated-overreceipt-rule-versions\/(\d+)\/name$/
      );
      if (selfOperatedRenameMatch && method === "PUT") {
        const id = Number(selfOperatedRenameMatch[1]);
        const { name } = JSON.parse(String(init?.body));
        selfOperatedRuleRows = selfOperatedRuleRows.map((rule) => (
          rule.id === id ? { ...rule, name } : rule
        ));
        return jsonResponse(selfOperatedRuleRows.find((rule) => rule.id === id));
      }
      if (url.endsWith("/api/overreceipt-rule-versions") && method === "POST") {
        if (failPublishOnce) {
          failPublishOnce = false;
          return jsonResponse({ detail: "发布服务暂时不可用" }, 500);
        }
        return jsonResponse({ ...firstRule, id: 2, name: "2026-08 新规则" }, 201);
      }
      const deliveryRenameMatch = url.match(
        /\/api\/overreceipt-rule-versions\/(\d+)\/name$/
      );
      if (deliveryRenameMatch && method === "PUT") {
        const id = Number(deliveryRenameMatch[1]);
        const { name } = JSON.parse(String(init?.body));
        deliveryRuleRows = deliveryRuleRows.map((rule) => (
          rule.id === id ? { ...rule, name } : rule
        ));
        return jsonResponse(deliveryRuleRows.find((rule) => rule.id === id));
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
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

    const confirmTitle = await screen.findByText(
      "确认发布自营仓超收规则？",
      { selector: ".ant-modal-confirm-title" }
    );
    const dialog = confirmTitle.closest<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(within(dialog!).getByText("2026-09 自营仓规则")).toBeInTheDocument();
    fireEvent.click(within(dialog!).getByRole("button", { name: "确认发布" }));

    await waitFor(() => {
      const post = vi.mocked(fetch).mock.calls.find(([input, init]) => (
        String(input).endsWith("/api/self-operated-overreceipt-rule-versions")
        && init?.method === "POST"
      ));
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
      vi.mocked(fetch).mock.calls.some(([input]) => (
        String(input).endsWith("/api/overreceipt-rule-versions/warehouses")
      ))
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
    expect(screen.getByText(/供应商成品本地仓/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-08 新规则" }
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "允许超收仓库" }));
    fireEvent.click(await screen.findByText("水鞋-广州仓", { selector: ".ant-select-item-option-content" }));
    expect(
      vi.mocked(fetch).mock.calls.filter(([input]) => (
        String(input).endsWith("/api/overreceipt-rule-versions/warehouses")
      ))
    ).toHaveLength(1);
    const drawerConfirmButton = screen.getByRole("button", { name: /确\s*认/ });
    expect(drawerConfirmButton).toHaveAttribute("type", "submit");
    expect(drawerConfirmButton).toHaveAttribute("form", "delivery-overreceipt-form");
    fireEvent.click(drawerConfirmButton);

    const confirmTitle = await screen.findByText(
      "确认发布不可变版本？",
      { selector: ".ant-modal-confirm-title" }
    );
    const dialog = confirmTitle.closest<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(within(dialog!).getByText("2026-08 新规则")).toBeInTheDocument();
    expect(within(dialog!).getByText("短尾 +50 件")).toBeInTheDocument();
    expect(within(dialog!).getByText("中尾 +20 件")).toBeInTheDocument();
    expect(within(dialog!).getByText("长尾 +10 件")).toBeInTheDocument();
    expect(within(dialog!).getByText("水鞋-广州仓")).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")
    ).toBe(false);
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
    expect(within(selfOperatedDialog).getByText(
      "只修改名称，不影响规则参数或历史批次"
    )).toBeInTheDocument();
    fireEvent.change(within(selfOperatedDialog).getByLabelText("版本名称"), {
      target: { value: "自营仓历史规则新名称" }
    });
    fireEvent.click(within(selfOperatedDialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => {
      const rename = vi.mocked(fetch).mock.calls.find(([input, init]) => (
        String(input).endsWith("/api/self-operated-overreceipt-rule-versions/10/name")
        && init?.method === "PUT"
      ));
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
      const rename = vi.mocked(fetch).mock.calls.find(([input, init]) => (
        String(input).endsWith("/api/overreceipt-rule-versions/1/name")
        && init?.method === "PUT"
      ));
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
});
