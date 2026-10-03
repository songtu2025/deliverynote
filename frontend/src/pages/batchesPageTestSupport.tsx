import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, expect, vi } from "vitest";
import { jsonResponse } from "./admin/positionDraftTestSupport";
export { jsonResponse } from "./admin/positionDraftTestSupport";

type BatchesTestState = {
  inboundSyncStatus: Record<string, unknown>;
  batchRows: Array<Record<string, unknown>>;
  deleteRequests: number[][];
};
export function rejectBatchRequest(status: number, detail: string, method = "GET") {
  const initialFetch = fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      (method === "GET" ? String(input).includes("/api/batches?") : init?.method === method)
        ? status === 0
          ? Promise.reject(new TypeError(detail))
          : Promise.resolve(new Response(JSON.stringify({ detail }), { status }))
        : initialFetch(input, init)
    )
  );
}

export async function submitBatchAction(action: "create" | "delete" | "clean") {
  if (action === "create") {
    fireEvent.click(await screen.findByRole("button", { name: /新建批次/ }));
    const dialog = await screen.findByRole("dialog");
    const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [new File(["synthetic"], "合成交货.xlsx")] } });
    const submit = within(dialog).getByRole("button", { name: "创建并上传文件" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
  } else if (action === "delete") {
    fireEvent.click(await screen.findByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" }));
    fireEvent.click(screen.getByRole("button", { name: "删除已选（1）" }));
    fireEvent.click(await screen.findByRole("button", { name: "永久删除" }));
  } else {
    fireEvent.click(await screen.findByRole("button", { name: /清理空批次/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^删\s*除$/ }));
  }
}

export function setFourteenBatches(state: BatchesTestState) {
  state.batchRows = Array.from({ length: 14 }, (_, index) => ({
    ...state.batchRows[0],
    id: index + 1,
    name: `交货批次 ${index + 1}`
  }));
}

export function FocusTestApp({ children }: PropsWithChildren) {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>{children}</AntApp>
    </ConfigProvider>
  );
}

export function setupBatchesPageTests() {
  const state: BatchesTestState = { inboundSyncStatus: {}, batchRows: [], deleteRequests: [] };
  beforeEach(() => {
    const versions = [
      "purchase",
      "product",
      "supplier",
      "position",
      "template",
      "inbound_template",
      "self_operated_inbound"
    ].map((kind, index) => ({
      id: index + 1,
      kind,
      name: `${kind}-v1`,
      original_name: `${kind}.xlsx`,
      active: true,
      created_by: 1,
      created_at: "2026-07-21T08:00:00"
    }));
    state.inboundSyncStatus = {
      configured: true,
      active_version: versions.find((version) => version.kind === "self_operated_inbound"),
      job: {
        id: 12,
        status: "succeeded",
        base_version_id: null,
        candidate_version_id: 7,
        total_orders: 8,
        raw_detail_count: 25,
        eligible_detail_count: 25,
        filtered_detail_count: 0,
        issue_count: 0,
        warning_count: 2,
        diff: { added_lines: 25, changed_lines: 0, removed_lines: 0, after_quantity: 120 },
        error_message: null,
        created_at: "2026-07-21T08:00:00",
        claimed_at: "2026-07-21T08:00:01",
        heartbeat_at: "2026-07-21T08:00:02",
        finished_at: "2026-07-21T08:00:03"
      }
    };
    state.batchRows = [
      {
        id: 7,
        name: "2026-07-21 交货批次",
        status: "succeeded",
        created_by: 1,
        version_ids: {},
        error_message: null,
        download_ready: false,
        created_at: "2026-07-21T08:00:00",
        updated_at: "2026-07-21T09:00:00",
        file_count: 2,
        summary: { delivery_total: 160, import_total: 100, manual_total: 60, conserved: true }
      }
    ];
    state.deleteRequests = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const url = String(input);
        if (url.endsWith("/api/batches") && init.method === "DELETE") {
          const payload = JSON.parse(String(init.body)) as { batch_ids: number[] };
          state.deleteRequests.push(payload.batch_ids);
          state.batchRows = state.batchRows.filter((batch) => !payload.batch_ids.includes(Number(batch.id)));
          return jsonResponse({
            deleted_count: payload.batch_ids.length,
            deleted_ids: payload.batch_ids,
            file_cleanup_failed_ids: []
          });
        }
        if (url.endsWith("/api/input-versions")) return jsonResponse(versions);
        if (url.endsWith("/api/purchase-sync")) return jsonResponse({ configured: true, job: null });
        if (url.endsWith("/api/overreceipt-rule-versions"))
          return jsonResponse([
            {
              id: 9,
              name: "短尾超收 V1",
              short_tail_limit: 50,
              medium_tail_limit: 20,
              long_tail_limit: 10,
              allowed_warehouses: ["水鞋-广州仓"],
              active: true,
              created_by: 1,
              created_at: "2026-07-21T08:00:00"
            }
          ]);
        if (url.endsWith("/api/self-operated-overreceipt-rule-versions"))
          return jsonResponse([
            {
              id: 10,
              name: "自营仓超收 5 件",
              allowance: 5,
              active: true,
              created_by: 1,
              created_at: "2026-07-21T08:00:00"
            }
          ]);
        if (url.endsWith("/api/self-operated-inbound-sync/12/preview?limit=100")) {
          return jsonResponse({
            columns: ["入库单号", "入库仓", "SKU", "平台站点", "关联交货单/调拨单", "关联采购单", "应收货"],
            rows: [
              {
                _row_number: 1,
                入库单号: "IN-1",
                入库仓: "自营仓",
                SKU: "SKU-A",
                平台站点: "AMAZON:SEEKWAY:US",
                "关联交货单/调拨单": "LN-1",
                关联采购单: "PO-1",
                应收货: 10
              }
            ],
            total: 1
          });
        }
        if (url.endsWith("/api/self-operated-inbound-sync/12/issues")) {
          return jsonResponse([
            {
              severity: "warning",
              message: "共享站点数据不能自动匹配",
              order_no: "IN-2",
              sku: "SKU-B",
              source_site: "共享",
              supplier_code: "SUP-1",
              supplier_name: "供应商 A",
              warehouse: "自营仓",
              remaining_quantity: 12,
              purchase_code: "PO-2",
              related_code: "LN-2",
              code: "shared_site"
            },
            {
              severity: "error",
              message: "关联采购单为空",
              order_no: "IN-3",
              sku: "SKU-C",
              source_site: "SEEKWAY:US",
              supplier_code: "SUP-2",
              supplier_name: "供应商 B",
              warehouse: "水鞋-广州仓",
              remaining_quantity: 8,
              purchase_code: "",
              related_code: "LN-3",
              code: "missing_purchase_code"
            }
          ]);
        }
        if (url.endsWith("/api/self-operated-inbound-sync")) return jsonResponse(state.inboundSyncStatus);
        if (url.includes("/api/batches?")) {
          const params = new URL(url, "http://localhost").searchParams;
          const workflow = params.get("workflow");
          const search = params.get("search")?.toLocaleLowerCase("zh-CN") ?? "";
          const status = params.get("batch_status");
          const matching = state.batchRows.filter(
            (batch) =>
              (batch.workflow ?? "delivery") === workflow &&
              String(batch.name).toLocaleLowerCase("zh-CN").includes(search) &&
              (!status || batch.status === status)
          );
          const offset = Number(params.get("offset") ?? 0);
          const limit = Number(params.get("limit") ?? 12);
          return jsonResponse({
            items: matching.slice(offset, offset + limit),
            total: matching.length,
            empty_draft_count: state.batchRows.filter(
              (batch) =>
                (batch.workflow ?? "delivery") === workflow &&
                batch.status === "draft" &&
                batch.file_count === 0 &&
                (workflow !== "self_operated_inbound" ||
                  !(batch.inbound_file as { uploaded?: boolean } | undefined)?.uploaded)
            ).length
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  return state;
}
