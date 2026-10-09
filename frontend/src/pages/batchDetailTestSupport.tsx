import { render as renderComponent } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import type { ReactElement } from "react";
import { beforeEach, afterEach, vi } from "vitest";
import type { SplitPart } from "../types";
import { jsonResponse } from "./admin/positionDraftTestSupport";
import { createDetailBatch, createDetailExceptions, fixtureVersion } from "./batch-detail/detailFixtures";
export const renderDetail = (ui: ReactElement) =>
  renderComponent(ui, {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>{children}</AntApp>
      </ConfigProvider>
    )
  });

export function setupBatchDetailTest() {
  const state = { batch: createDetailBatch(), exceptions: createDetailExceptions() };
  const exceptionPage = (url: string) => {
    const params = new URL(url, "http://localhost").searchParams;
    const scope = params.get("review_scope");
    const rows = state.exceptions.filter(
      (item) =>
        (scope !== "resolved" || item.status === "resolved") &&
        (scope !== "unfinished" || item.status !== "resolved") &&
        (!params.get("reason") || item.reason === params.get("reason")) &&
        (!params.get("site") || item.full_site === params.get("site")) &&
        (!params.get("scale_position") || item.scale_position === params.get("scale_position")) &&
        (!params.get("stocking_position") || item.stocking_position === params.get("stocking_position")) &&
        String(item.sku).includes(params.get("search") ?? "")
    );
    const offset = Number(params.get("offset") ?? 0);
    const limit = Number(params.get("limit") ?? 10);
    const unfinished = state.exceptions.filter((item) => item.status !== "resolved");
    return {
      items: rows.slice(offset, offset + limit),
      total: rows.length,
      stats: {
        unfinished_count: unfinished.length,
        unfinished_quantity: unfinished.reduce(
          (sum, item) =>
            sum +
            (item.parts.length
              ? item.parts
                  .filter((part: { resolved: boolean }) => !part.resolved)
                  .reduce((partSum: number, part: { quantity: number }) => partSum + part.quantity, 0)
              : item.manual_quantity),
          0
        ),
        resolved_count: state.exceptions.length - unfinished.length,
        total_count: state.exceptions.length
      }
    };
  };

  const exceptionFilters = () => ({
    reasons: [...new Set(state.exceptions.map((item) => item.reason))],
    sites: [...new Set(state.exceptions.map((item) => item.full_site))],
    scales: [...new Set(state.exceptions.map((item) => item.scale_position).filter(Boolean))],
    stocking: [...new Set(state.exceptions.map((item) => item.stocking_position).filter(Boolean))]
  });

  const pagedExceptions = () =>
    Array.from({ length: 12 }, (_, index) => ({
      ...state.exceptions[0],
      id: 100 + index,
      sku: `SKU-${index + 1}`,
      manual_quantity: 1
    }));

  beforeEach(() => {
    state.batch = createDetailBatch();
    state.exceptions = createDetailExceptions();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/auth/me")) return jsonResponse({ id: 1, username: "admin", role: "admin" });
        if (url.endsWith("/api/batches/7/exceptions/filters")) return jsonResponse(exceptionFilters());
        if (url.includes("/api/batches/7/exceptions?")) return jsonResponse(exceptionPage(url));
        if (url.endsWith("/api/input-versions")) {
          return jsonResponse([{ ...fixtureVersion(9, "supplier"), name: "supplier-v2" }]);
        }
        if (url.endsWith("/api/batches/7/refresh-supplier-version") && init?.method === "POST") {
          state.batch = {
            ...state.batch,
            version_ids: { ...state.batch.version_ids, supplier: 9 },
            versions: {
              ...state.batch.versions,
              supplier: { ...fixtureVersion(9, "supplier"), name: "supplier-v2" }
            }
          };
          return jsonResponse(state.batch);
        }
        if (url.endsWith("/api/batches/7")) return jsonResponse(state.batch);
        if (url.endsWith("/api/jobs/88")) return jsonResponse(state.batch.jobs.compute ?? state.batch.jobs.export);
        const splitMatch = url.match(/\/api\/exceptions\/(\d+)\/split$/);
        if (splitMatch && init?.method === "PUT") {
          const exceptionId = Number(splitMatch[1]);
          const parts = JSON.parse(String(init.body)).parts as SplitPart[];
          const resolvedCount = parts.filter((part) => part.resolved).length;
          const updated = {
            ...state.exceptions.find((item) => item.id === exceptionId)!,
            parts,
            status: resolvedCount === parts.length ? "resolved" : resolvedCount ? "partial" : "pending"
          };
          state.exceptions = state.exceptions.map((item) => (item.id === exceptionId ? updated : item));
          return jsonResponse(updated);
        }
        const selfOperatedSiteMatch = url.match(/\/api\/exceptions\/(\d+)\/self-operated-site$/);
        if (selfOperatedSiteMatch && init?.method === "PUT") {
          return jsonResponse({ id: 99, kind: "compute", status: "queued" });
        }
        if (url.endsWith("/api/batches/7/download-merged")) {
          return new Response("merged", { status: 200 });
        }
        if (url.endsWith("/api/batches/7/download")) {
          return new Response("zip", { status: 200 });
        }
        if (url.endsWith("/api/batches/7/files/order") && init?.method === "PUT") {
          return jsonResponse(state.batch);
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  return { state, exceptionPage, exceptionFilters, pagedExceptions };
}
