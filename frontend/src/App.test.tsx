import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";


describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/auth/login")) {
          return new Response(
            JSON.stringify({
              token: "token-1",
              user: { id: 1, username: "admin", role: "admin", active: true }
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (url.endsWith("/api/batches")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        if (url.endsWith("/api/input-versions")) {
          return new Response(JSON.stringify([]), {
            status: 200,
            headers: { "Content-Type": "application/json" }
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("logs in and opens the batch workspace", async () => {
    render(<App />);

    fireEvent.change(screen.getByLabelText("用户名"), {
      target: { value: "admin" }
    });
    fireEvent.change(screen.getByLabelText("密码"), {
      target: { value: "admin-pass" }
    });
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));

    await screen.findByText("交货批次");
    expect(screen.getByText("管理员维护")).toBeInTheDocument();
    expect(localStorage.getItem("delivery-note-token")).toBe("token-1");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  });

  it("returns to login when a stored session expires", async () => {
    localStorage.setItem("delivery-note-token", "expired-token");
    localStorage.setItem("delivery-note-user", JSON.stringify({
      id: 1,
      username: "admin",
      role: "admin",
      active: true
    }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "未登录" }),
      { status: 401, headers: { "Content-Type": "application/json" } }
    )));

    render(<App />);

    await screen.findByRole("button", { name: /登\s*录/ });
    expect(localStorage.getItem("delivery-note-token")).toBeNull();
    expect(localStorage.getItem("delivery-note-user")).toBeNull();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });
});
