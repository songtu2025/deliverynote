import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OverreceiptRulesPage from "../OverreceiptRulesPage";
import { api, AUTH_EXPIRED_EVENT } from "../../api";
import { jsonResponse, deferred } from "../admin/positionDraftTestSupport";
import { render, setupRuleTests, selfOperatedRule, previousSelfOperatedRule } from "./ruleTestSupport";

setupRuleTests();

describe("OverreceiptRulesPage", () => {
  it("ignores an older read that arrives after a newer read", async () => {
    const originalFetch = fetch;
    const { promise: pending, resolve: resolveOld } = deferred<Response>();
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
  it("刷新返回的旧名称不能覆盖已保存的重命名", async () => {
    const view = render(<OverreceiptRulesPage />);
    await screen.findByText(selfOperatedRule.name);
    const originalFetch = fetch;
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("/api/self-operated-overreceipt-rule-versions") && !init?.method
          ? pending.promise
          : originalFetch(input, init)
      )
    );
    fireEvent.click(screen.getByRole("button", { name: /刷\s*新/ }));
    fireEvent.click(screen.getByRole("button", { name: `重命名 ${previousSelfOperatedRule.name}` }));
    fireEvent.change(screen.getByLabelText("版本名称"), { target: { value: "已保存的新名称" } });
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
    expect(await screen.findByText("已保存的新名称")).toBeInTheDocument();
    await act(async () => pending.resolve(jsonResponse([selfOperatedRule, previousSelfOperatedRule])));
    expect(screen.getByText("已保存的新名称")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: `重命名 ${previousSelfOperatedRule.name}` })).not.toBeInTheDocument();
    view.unmount();
  });
});
