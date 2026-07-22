import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const jsonResponse = (payload: unknown, status = 200) => new Response(
  JSON.stringify(payload),
  { status, headers: { "Content-Type": "application/json" } }
);

describe("OverreceiptRulesPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/overreceipt-rule-versions/warehouses")) {
        return jsonResponse(["供应链成品仓", "水鞋-广州仓"]);
      }
      if (url.endsWith("/api/overreceipt-rule-versions") && method === "GET") {
        return jsonResponse([firstRule]);
      }
      if (url.endsWith("/api/overreceipt-rule-versions") && method === "POST") {
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
    expect(screen.getByText("供应链成品仓")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("规则版本名称"), {
      target: { value: "2026-08 新规则" }
    });
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "允许超收仓库" }));
    fireEvent.click(await screen.findByText("水鞋-广州仓", { selector: ".ant-select-item-option-content" }));
    fireEvent.click(screen.getByRole("button", { name: "发布并用于新批次" }));

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
});
