import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import OverreceiptRulesPage from "../OverreceiptRulesPage";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";
import { render, setupRuleTests, selfOperatedRule, previousRule, previousSelfOperatedRule } from "./ruleTestSupport";

setupRuleTests();

const cases = ["delivery", "self_operated"].flatMap((scope) =>
  ["publish", "rename", "activate"].flatMap((action) =>
    ["hidden", "unmounted"].flatMap((exit) => [200, 500].map((status) => ({ scope, action, exit, status })))
  )
);

describe("离开超收规则页后的写响应", () => {
  it.each(cases)("$scope $action 在 $exit 后收到 $status 不再更新或提示", async ({ scope, action, exit, status }) => {
    const pending = deferred<Response>();
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        init?.method === "POST" || init?.method === "PUT" ? pending.promise : originalFetch(input, init)
      )
    );
    const view = render(<OverreceiptRulesPage />);
    await screen.findByText(selfOperatedRule.name);
    if (scope === "delivery") fireEvent.click(screen.getByRole("button", { name: /^交货超收/ }));
    const previous = scope === "delivery" ? previousRule : previousSelfOperatedRule;
    if (action === "activate") {
      fireEvent.click(screen.getByRole("button", { name: `重新启用 ${previous.name}` }));
    } else if (action === "rename") {
      fireEvent.click(screen.getByRole("button", { name: `重命名 ${previous.name}` }));
      const dialog = await screen.findByRole("dialog", { name: "修改版本名称" });
      fireEvent.change(within(dialog).getByLabelText("版本名称"), { target: { value: "迟到的新名称" } });
      fireEvent.click(within(dialog).getByRole("button", { name: /保\s*存/ }));
    } else {
      fireEvent.click(screen.getByRole("button", { name: /发布新版本/ }));
      fireEvent.change(screen.getByLabelText("规则版本名称"), { target: { value: "迟到的发布" } });
      fireEvent.click(screen.getByRole("button", { name: /确\s*认/ }));
      fireEvent.click(await screen.findByRole("button", { name: "确认发布" }));
    }
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method)).toHaveLength(1));
    const reads = vi.mocked(fetch).mock.calls.filter(([, init]) => !init?.method).length;
    if (exit === "hidden") view.rerender(<OverreceiptRulesPage active={false} />);
    else view.unmount();
    await act(async () => {
      pending.resolve(
        jsonResponse(status === 500 ? { detail: "迟到的写错误" } : { ...previous, name: "迟到的新名称" }, status)
      );
    });
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => !init?.method)).toHaveLength(reads);
    expect(screen.queryByText("迟到的写错误")).not.toBeInTheDocument();
    expect(screen.queryByText("版本名称已更新")).not.toBeInTheDocument();
    expect(screen.queryByText(/已发布，将用于新批次|已重新启用/)).not.toBeInTheDocument();
    if (exit === "hidden" && action === "rename") {
      expect(screen.getByRole("button", { name: `重命名 ${previous.name}` })).toBeInTheDocument();
    }
  });
});
