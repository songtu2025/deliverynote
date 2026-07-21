import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminPage from "./AdminPage";

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { "Content-Type": "application/json" }
});

describe("AdminPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/users")) {
        return jsonResponse([{ id: 1, username: "admin", role: "admin", active: true }]);
      }
      if (url.endsWith("/api/input-versions")) return jsonResponse([]);
      if (url.endsWith("/api/audit-logs")) {
        return jsonResponse([{
          id: 1,
          user_id: null,
          action: "worker_compute_succeeded",
          entity_type: "batch",
          entity_id: "7",
          details: {},
          created_at: "2026-07-21T09:00:00"
        }]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows readiness, user safeguards, and audit history", async () => {
    render(<AdminPage currentUser={{ id: 1, username: "admin", role: "admin", active: true }} />);

    await screen.findByText("基础资料未就绪（0/5）");
    fireEvent.click(screen.getByRole("tab", { name: "用户管理" }));
    await screen.findByText("内部账号");
    await screen.findByText("admin");
    expect(screen.getByRole("button", { name: /停\s*用/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("tab", { name: /操作记录/ }));
    expect(await screen.findByText("系统 Worker")).toBeInTheDocument();
    expect(screen.getByText("计算完成")).toBeInTheDocument();
  }, 30_000);
});
