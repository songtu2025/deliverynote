import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, download } from "./api";

describe("browser API authentication", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("delivery-note-token", "legacy-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses cookies without reading or sending the legacy bearer token", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ status: "ok" }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    )));

    await api<{ status: string }>("/api/example");

    expect(getItem).not.toHaveBeenCalled();
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(init).toEqual(expect.objectContaining({ credentials: "include" }));
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
  });

  it("includes cookies and omits Authorization for downloads", async () => {
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("file")));

    await download("/api/example/download", "example.xlsx");

    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(init).toEqual(expect.objectContaining({ credentials: "include" }));
    expect(new Headers(init?.headers).has("Authorization")).toBe(false);
  });

  it("explains login throttling when the gateway returns HTML", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<h1>429</h1>", {
      status: 429,
      headers: { "Content-Type": "text/html" }
    })));

    await expect(api("/api/auth/login", { method: "POST" }))
      .rejects.toThrow("登录尝试过于频繁，请稍后再试");
  });
});
