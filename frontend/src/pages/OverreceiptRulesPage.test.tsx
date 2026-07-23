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

const jsonResponse = (payload: unknown, status = 200) => new Response(
  JSON.stringify(payload),
  { status, headers: { "Content-Type": "application/json" } }
);

let failPublishOnce = false;

describe("OverreceiptRulesPage", () => {
  beforeEach(() => {
    failPublishOnce = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/overreceipt-rule-versions/warehouses")) {
        return jsonResponse(["供应商成品本地仓", "水鞋-广州仓"]);
      }
      if (url.endsWith("/api/overreceipt-rule-versions") && method === "GET") {
        return jsonResponse([firstRule, previousRule]);
      }
      if (url.endsWith("/api/overreceipt-rule-versions") && method === "POST") {
        if (failPublishOnce) {
          failPublishOnce = false;
          return jsonResponse({ detail: "发布服务暂时不可用" }, 500);
        }
        return jsonResponse({ ...firstRule, id: 2, name: "2026-08 新规则" }, 201);
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the active immutable version and publishes an exact warehouse whitelist", async () => {
    render(<OverreceiptRulesPage />);

    await screen.findByText("当前启用版本");
    expect(screen.getAllByText("2026-07 短尾放宽").length).toBeGreaterThan(0);
    expect(screen.getAllByText("短尾 +50").length).toBeGreaterThan(0);
    expect(screen.getAllByText("中尾 +20").length).toBeGreaterThan(0);
    expect(screen.getAllByText("长尾 +10").length).toBeGreaterThan(0);
    expect(screen.getByText("供应商成品本地仓")).toBeInTheDocument();
    expect(screen.queryByText("供应链成品仓")).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: "超收规则不可变版本" })).toBeInTheDocument();
    expect(screen.getAllByText("未开放任何仓库").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "重新启用 2026-06 基线规则" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-08 新规则" }
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "允许超收仓库" }));
    fireEvent.click(await screen.findByText("水鞋-广州仓", { selector: ".ant-select-item-option-content" }));
    fireEvent.click(screen.getByRole("button", { name: "发布并用于新批次" }));

    const dialog = await screen.findByRole("dialog", { name: "确认发布不可变版本？" });
    expect(within(dialog).getByText("2026-08 新规则")).toBeInTheDocument();
    expect(within(dialog).getByText("短尾 +50 件")).toBeInTheDocument();
    expect(within(dialog).getByText("中尾 +20 件")).toBeInTheDocument();
    expect(within(dialog).getByText("长尾 +10 件")).toBeInTheDocument();
    expect(within(dialog).getByText("水鞋-广州仓")).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")
    ).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));

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
  });

  it("keeps a failed publication confirmation open and allows retry", async () => {
    failPublishOnce = true;
    render(<OverreceiptRulesPage />);

    await screen.findByText("当前启用版本");
    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-08 重试规则" }
    });
    fireEvent.click(screen.getByRole("button", { name: "发布并用于新批次" }));

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
