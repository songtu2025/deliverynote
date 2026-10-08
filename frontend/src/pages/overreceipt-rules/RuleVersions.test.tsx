import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OverreceiptRulesPage from "../OverreceiptRulesPage";
import { api } from "../../api";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import {
  render,
  setupRuleTests,
  firstRule,
  previousRule,
  selfOperatedRule,
  previousSelfOperatedRule,
  rulesTestState
} from "./ruleTestSupport";

setupRuleTests();

describe("OverreceiptRulesPage", () => {
  it("keeps the current version out of an empty history state", async () => {
    rulesTestState.deliveryRuleRows = [firstRule];
    rulesTestState.selfOperatedRuleRows = [selfOperatedRule];

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
      screen.getByLabelText(`重新启用 ${scope === "delivery" ? previousRule.name : previousSelfOperatedRule.name}`);
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
  it.each(["delivery", "self_operated"])("重新启用 %s 历史版本，当前版本移入历史", async (scope) => {
    render(<OverreceiptRulesPage />);
    await screen.findByText(selfOperatedRule.name);
    const previous = scope === "delivery" ? previousRule : previousSelfOperatedRule;
    const current = scope === "delivery" ? firstRule : selfOperatedRule;
    if (scope === "delivery") fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    fireEvent.click(screen.getByRole("button", { name: `重新启用 ${previous.name}` }));
    const table = () =>
      screen.getByRole("table", { name: scope === "delivery" ? "超收规则不可变版本" : "自营仓超收规则历史版本" });
    await waitFor(() => expect(within(table()).queryByText(previous.name)).not.toBeInTheDocument());
    expect(within(table()).getByText(current.name)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `重命名 ${previous.name}` })).toBeInTheDocument();
    expect(
      await screen.findByText(`已重新启用 ${previous.name}，仅影响新建${scope === "delivery" ? "" : "自营仓"}批次`)
    ).toBeInTheDocument();
    const requests = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/activate"));
    expect(requests).toHaveLength(1);
    expect(requests[0][1]?.method).toBe("POST");
  });
});
