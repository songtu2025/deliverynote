import { useCallback, useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { InputVersion } from "../types";
import PurchaseSyncPanel from "./PurchaseSyncPanel";

const activeVersion: InputVersion = {
  id: 1,
  kind: "purchase",
  name: "purchase-current",
  original_name: "purchase.xlsx",
  active: true,
  created_by: 1,
  created_at: "2026-08-25T01:00:00Z"
};

const candidateVersion: InputVersion = {
  ...activeVersion,
  id: 8,
  name: "积加同步候选",
  original_name: "gerpgo.xlsx",
  active: false
};

const succeededJob = {
  id: 9,
  status: "succeeded",
  base_version_id: 1,
  product_version_id: null,
  supplier_version_id: null,
  candidate_version_id: 8,
  total_orders: 129,
  processed_orders: 129,
  raw_detail_count: 9437,
  eligible_detail_count: 4196,
  filtered_detail_count: 5241,
  current_order: null,
  issue_count: 1,
  warning_count: 1,
  diff: { added_lines: 3, changed_lines: 5, removed_lines: 2, after_quantity: 860 },
  error_message: null,
  created_at: "2026-08-25T01:00:00Z",
  claimed_at: "2026-08-25T01:00:01Z",
  heartbeat_at: "2026-08-25T01:03:00Z",
  finished_at: "2026-08-25T01:03:00Z"
};

const jsonResponse = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "Content-Type": "application/json" }
});

describe("PurchaseSyncPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/purchase-sync") && method === "GET") {
        return jsonResponse({ configured: true, job: succeededJob });
      }
      if (url.endsWith("/api/purchase-sync") && method === "POST") {
        return jsonResponse({ ...succeededJob, status: "queued" }, 201);
      }
      if (url.endsWith("/api/purchase-sync/9/issues")) {
        return jsonResponse([{
          severity: "warning",
          message: "共享站点数据不能参与正常交货匹配",
          po_code: "PO-1001",
          sku: "SKU-A",
          source_site: "共享",
          supplier_code: "SUP-1",
          supplier_name: "供应商 A",
          warehouse: "水鞋-广州仓",
          quantity: 12,
          code: "shared_site"
        }]);
      }
      if (url.endsWith("/api/purchase-sync/9/preview?limit=100")) {
        return jsonResponse({
          columns: ["单据状态", "供应商", "SKU", "平台站点", "目的仓", "未交量"],
          rows: [{
            单据状态: "待交货",
            供应商: "供应商 A",
            SKU: "SKU-A",
            平台站点: "AMAZON:SEEKWAY:US",
            目的仓: "水鞋-广州仓",
            未交量: 12
          }],
          total: 1
        });
      }
      if (url.endsWith("/api/input-versions/8/activate") && method === "POST") {
        return jsonResponse({ ...candidateVersion, active: true });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("lets operators preview candidate data and issues without activating the candidate", async () => {
    render(
      <PurchaseSyncPanel
        versions={[activeVersion, candidateVersion]}
        canActivate={false}
        refreshVersions={vi.fn(async () => [activeVersion, candidateVersion])}
      />
    );

    expect(await screen.findByText("同步完成，待启用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /同步采购数据/ })).toBeInTheDocument();
    expect(screen.getByText("待管理员启用")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "启用最新数据" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /预览候选数据/ }));
    const previewDialog = await screen.findByRole("dialog", { name: "采购候选数据预览" });
    expect(within(previewDialog).getByRole("columnheader", { name: "SKU" })).toBeInTheDocument();
    expect(within(previewDialog).getByRole("columnheader", { name: "目的仓" })).toBeInTheDocument();
    expect(within(previewDialog).getByRole("columnheader", { name: "未交量" })).toBeInTheDocument();
    expect(within(previewDialog).getByText("AMAZON:SEEKWAY:US")).toBeInTheDocument();
    fireEvent.click(within(previewDialog).getByRole("button", { name: "Close" }));

    fireEvent.click(screen.getByRole("button", { name: "查看异常数据" }));
    const dialog = await screen.findByRole("dialog", { name: "采购同步异常数据" });
    expect(within(dialog).getByRole("columnheader", { name: "目的仓" })).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "未交量" })).toBeInTheDocument();
    expect(await within(dialog).findByText("PO-1001")).toBeInTheDocument();
    expect(within(dialog).getByText("水鞋-广州仓")).toBeInTheDocument();
    expect(within(dialog).getByText("12")).toBeInTheDocument();
  });

  it("keeps candidate activation available to administrators", async () => {
    const refreshVersions = vi.fn(async () => [{ ...candidateVersion, active: true }]);
    render(
      <PurchaseSyncPanel
        versions={[activeVersion, candidateVersion]}
        canActivate
        refreshVersions={refreshVersions}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "启用最新数据" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认启用" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/input-versions/8/activate",
      expect.objectContaining({ method: "POST" })
    ));
    expect(refreshVersions).toHaveBeenCalled();
  });

  it("polls only purchase status and refreshes versions once on completion", async () => {
    vi.useFakeTimers();
    const requests: string[] = [];
    let statusRequestCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url.replace(/^.*(?=\/api\/)/, ""));
      statusRequestCount += 1;
      return jsonResponse({
        configured: true,
        job: statusRequestCount < 3
          ? { ...succeededJob, status: "running", candidate_version_id: null }
          : succeededJob
      });
    }));
    const refreshed = vi.fn();

    function Harness() {
      const [versions, setVersions] = useState([activeVersion]);
      const refreshVersions = useCallback(async () => {
        refreshed();
        const nextVersions = [activeVersion, candidateVersion];
        setVersions(nextVersions);
        return nextVersions;
      }, []);
      return (
        <PurchaseSyncPanel
          versions={versions}
          canActivate
          refreshVersions={refreshVersions}
        />
      );
    }

    render(<Harness />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    requests.length = 0;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(requests).toEqual(["/api/purchase-sync"]);
    expect(refreshed).not.toHaveBeenCalled();
    requests.length = 0;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(requests).toEqual(["/api/purchase-sync"]);
    expect(refreshed).toHaveBeenCalledTimes(1);
  });
});
