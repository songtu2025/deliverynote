import type { ReactElement } from "react";
import { render as renderComponent } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, vi } from "vitest";
import { jsonResponse } from "../admin/positionDraftTestSupport";

export const render = (ui: ReactElement) => renderComponent(ui, { wrapper: AntApp });

export const firstRule = {
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

export const previousRule = {
  ...firstRule,
  id: 0,
  name: "2026-06 基线规则",
  allowed_warehouses: [],
  active: false,
  created_at: "2026-06-22T08:00:00"
};

export const selfOperatedRule = {
  id: 11,
  name: "Windows验收-每键超收5件",
  allowance: 5,
  active: true,
  created_by: 1,
  created_at: "2026-08-24T04:08:41Z"
};

export const previousSelfOperatedRule = {
  ...selfOperatedRule,
  id: 10,
  name: "自营仓基线规则",
  allowance: 3,
  active: false,
  created_at: "2026-08-20T04:08:41Z"
};

export const rulesTestState = {
  failPublishOnce: false,
  deliveryRuleRows: [firstRule, previousRule],
  selfOperatedRuleRows: [selfOperatedRule, previousSelfOperatedRule]
};

export function setupRuleTests() {
  beforeEach(() => {
    rulesTestState.failPublishOnce = false;
    rulesTestState.deliveryRuleRows = [firstRule, previousRule];
    rulesTestState.selfOperatedRuleRows = [selfOperatedRule, previousSelfOperatedRule];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/api/auth/me")) return jsonResponse({ id: 1 });
        if (url.endsWith("/api/overreceipt-rule-versions/warehouses")) {
          return jsonResponse(["供应商成品本地仓", "水鞋-广州仓"]);
        }
        const activation = url.match(/\/api\/(self-operated-)?overreceipt-rule-versions\/(\d+)\/activate$/);
        if (activation && method === "POST") {
          const id = Number(activation[2]);
          if (activation[1]) {
            rulesTestState.selfOperatedRuleRows = rulesTestState.selfOperatedRuleRows.map((rule) => ({
              ...rule,
              active: rule.id === id
            }));
            return jsonResponse(rulesTestState.selfOperatedRuleRows.find((rule) => rule.id === id));
          }
          rulesTestState.deliveryRuleRows = rulesTestState.deliveryRuleRows.map((rule) => ({
            ...rule,
            active: rule.id === id
          }));
          return jsonResponse(rulesTestState.deliveryRuleRows.find((rule) => rule.id === id));
        }
        if (url.endsWith("/api/overreceipt-rule-versions") && method === "GET") {
          return jsonResponse(rulesTestState.deliveryRuleRows);
        }
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions") && method === "GET") {
          return jsonResponse(rulesTestState.selfOperatedRuleRows);
        }
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions") && method === "POST") {
          return jsonResponse({ ...selfOperatedRule, id: 12, name: "2026-09 自营仓规则" }, 201);
        }
        const selfOperatedRenameMatch = url.match(/\/api\/self-operated-overreceipt-rule-versions\/(\d+)\/name$/);
        if (selfOperatedRenameMatch && method === "PUT") {
          const id = Number(selfOperatedRenameMatch[1]);
          const { name } = JSON.parse(String(init?.body));
          rulesTestState.selfOperatedRuleRows = rulesTestState.selfOperatedRuleRows.map((rule) =>
            rule.id === id ? { ...rule, name } : rule
          );
          return jsonResponse(rulesTestState.selfOperatedRuleRows.find((rule) => rule.id === id));
        }
        if (url.endsWith("/api/overreceipt-rule-versions") && method === "POST") {
          if (rulesTestState.failPublishOnce) {
            rulesTestState.failPublishOnce = false;
            return jsonResponse({ detail: "发布服务暂时不可用" }, 500);
          }
          return jsonResponse({ ...firstRule, id: 2, name: "2026-08 新规则" }, 201);
        }
        const deliveryRenameMatch = url.match(/\/api\/overreceipt-rule-versions\/(\d+)\/name$/);
        if (deliveryRenameMatch && method === "PUT") {
          const id = Number(deliveryRenameMatch[1]);
          const { name } = JSON.parse(String(init?.body));
          rulesTestState.deliveryRuleRows = rulesTestState.deliveryRuleRows.map((rule) =>
            rule.id === id ? { ...rule, name } : rule
          );
          return jsonResponse(rulesTestState.deliveryRuleRows.find((rule) => rule.id === id));
        }
        throw new Error(`Unexpected request: ${method} ${url}`);
      })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
}
