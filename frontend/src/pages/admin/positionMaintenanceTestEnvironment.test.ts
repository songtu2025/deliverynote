import { describe, expect, it, vi } from "vitest";

import type { PositionIssue } from "../../types";
import { baseDraft, baseRow, baseValidation, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";

describe("position maintenance test environment", () => {
  it("isolates nested draft, row and validation data from other environments and the shared fixtures", () => {
    const first = createPositionMaintenanceTestEnvironment();
    const second = createPositionMaintenanceTestEnvironment();
    const baseline = structuredClone({ baseDraft, baseRow, baseValidation });
    const issue: PositionIssue = { severity: "warning", code: "test", message: "隔离测试", row_numbers: [2] };
    const diff = first.state.draftResponse.diff;
    expect(diff).toBeDefined();
    if (diff) diff.added = 99;
    first.state.draftResponse.issues.push(issue);
    first.state.rowsResponse.rows[0].msku = "ONLY-FIRST";
    first.state.rowsResponse.rows[0].issues.push(issue);
    first.state.validationResponse.diff.added = 88;
    first.state.validationResponse.issues.push(issue);

    expect(second.state.draftResponse).toEqual(baseline.baseDraft);
    expect(second.state.rowsResponse.rows).toEqual([baseline.baseRow]);
    expect(second.state.validationResponse).toEqual(baseline.baseValidation);
    expect({ baseDraft, baseRow, baseValidation }).toEqual(baseline);
  });

  it("keeps failure switches and response handlers local to one environment", async () => {
    const first = createPositionMaintenanceTestEnvironment();
    first.state.failEntry = true;
    first.state.conflictNextRowWrite = true;
    first.state.rowRequestHandler = () => jsonResponse({ detail: "仅第一个环境读取失败" }, 500);
    const second = createPositionMaintenanceTestEnvironment();

    expect((await first.fetch("/api/input-drafts/position", { method: "POST" })).status).toBe(500);
    expect((await second.fetch("/api/input-drafts/position", { method: "POST" })).status).toBe(200);
    expect((await second.fetch("/api/input-drafts/7/rows", { method: "POST" })).status).toBe(201);
    const conflict = await first.fetch("/api/input-drafts/7/rows", { method: "POST" });
    expect(conflict.status).toBe(409);
    expect(await conflict.json()).toMatchObject({ code: "draft_revision_conflict" });
    expect((await first.fetch("/api/input-drafts/7/rows", { method: "POST" })).status).toBe(201);
    expect((await first.fetch("/api/input-drafts/7/rows?offset=0&limit=20")).status).toBe(500);
    expect(await (await second.fetch("/api/input-drafts/7/rows?offset=0&limit=20")).json()).toEqual(
      second.state.rowsResponse
    );
  });

  it("keeps delayed responses bound to their original environment", async () => {
    const first = createPositionMaintenanceTestEnvironment();
    const response = deferred<Response>();
    first.state.metadataRequest = response;
    let settled = false;
    const pending = first.fetch("/api/input-drafts/position").then((result) => {
      settled = true;
      return result;
    });
    const second = createPositionMaintenanceTestEnvironment();
    expect(await (await second.fetch("/api/input-drafts/position")).json()).toEqual(baseDraft);
    expect(settled).toBe(false);

    response.resolve(jsonResponse({ ...baseDraft, revision: 91 }));
    expect(await (await pending).json()).toMatchObject({ revision: 91 });
    expect(second.state.draftResponse.revision).toBe(baseDraft.revision);
  });

  it("records requests separately and forwards the complete filter URL to the scenario handler", async () => {
    const first = createPositionMaintenanceTestEnvironment();
    const second = createPositionMaintenanceTestEnvironment();
    const url = "http://test/api/input-drafts/7/rows?offset=20&limit=20&search=SKU-A";
    first.state.rowRequestHandler = vi.fn(() => jsonResponse(first.state.rowsResponse));
    await first.fetch(url);
    await second.fetch("/api/input-drafts/position", { method: "POST" });

    expect(first.state.rowRequestHandler).toHaveBeenCalledWith(url);
    expect(first.fetch.mock.calls).toEqual([[url]]);
    expect(second.fetch.mock.calls).toEqual([["/api/input-drafts/position", { method: "POST" }]]);
    expect(first.requests("GET", "/rows?")).toEqual([[url]]);
    expect(first.requests("POST", "/rows?")).toEqual([]);
    expect(first.requests("GET", "/unknown")).toEqual([]);
    expect(second.requests("POST", "/position")).toEqual([["/api/input-drafts/position", { method: "POST" }]]);
    expect(second.requests("GET", "/rows?")).toEqual([]);
    expect(createPositionMaintenanceTestEnvironment().fetch).not.toHaveBeenCalled();
  });

  it.each([
    ["PUT", "/api/input-drafts/position"],
    ["POST", "/api/input-drafts/8/rows"],
    ["GET", "/api/input-drafts/7/rows/999"],
    ["GET", "/api/unknown"]
  ])("rejects an unmatched %s %s instead of returning a successful fallback", async (method, url) => {
    const environment = createPositionMaintenanceTestEnvironment();
    await expect(environment.fetch(url, { method })).rejects.toThrow(`Unexpected request: ${method} ${url}`);
  });

  it("restores the previous global fetch and spies when the installed environment is disposed", async () => {
    const originalFetch = globalThis.fetch;
    const target = { callback: () => "original" };
    const originalCallback = target.callback;
    const environment = createPositionMaintenanceTestEnvironment();
    try {
      vi.spyOn(target, "callback").mockReturnValue("changed");
      environment.install();
      expect(globalThis.fetch).toBe(environment.fetch);
      expect(target.callback()).toBe("changed");
      await fetch("/api/input-drafts/position", { method: "POST" });
      expect(environment.fetch).toHaveBeenCalledOnce();

      environment.dispose();
      expect(globalThis.fetch).toBe(originalFetch);
      expect(target.callback).toBe(originalCallback);
      expect(target.callback()).toBe("original");
    } finally {
      environment.dispose();
    }
  });
});
