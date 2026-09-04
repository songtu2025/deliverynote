import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BatchesPage from "./BatchesPage";

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { "Content-Type": "application/json" }
});

let inboundSyncStatus: Record<string, unknown>;
let batchRows: Array<Record<string, unknown>>;
let deleteRequests: number[][];

describe("BatchesPage", () => {
  beforeEach(() => {
    const versions = ["purchase", "product", "supplier", "position", "template", "inbound_template", "self_operated_inbound"].map((kind, index) => ({
      id: index + 1,
      kind,
      name: `${kind}-v1`,
      original_name: `${kind}.xlsx`,
      active: true,
      created_by: 1,
      created_at: "2026-07-21T08:00:00"
    }));
    inboundSyncStatus = {
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
    batchRows = [{
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
    }];
    deleteRequests = [];
    vi.stubGlobal("fetch", vi.fn(async (
      input: RequestInfo | URL,
      init: RequestInit = {}
    ) => {
      const url = String(input);
      if (url.endsWith("/api/batches") && init.method === "DELETE") {
        const payload = JSON.parse(String(init.body)) as { batch_ids: number[] };
        deleteRequests.push(payload.batch_ids);
        batchRows = batchRows.filter((batch) => !payload.batch_ids.includes(Number(batch.id)));
        return jsonResponse({
          deleted_count: payload.batch_ids.length,
          deleted_ids: payload.batch_ids,
          file_cleanup_failed_ids: []
        });
      }
      if (url.endsWith("/api/input-versions")) return jsonResponse(versions);
      if (url.endsWith("/api/purchase-sync")) return jsonResponse({ configured: true, job: null });
      if (url.endsWith("/api/overreceipt-rule-versions")) return jsonResponse([{
        id: 9,
        name: "短尾超收 V1",
        short_tail_limit: 50,
        medium_tail_limit: 20,
        long_tail_limit: 10,
        allowed_warehouses: ["水鞋-广州仓"],
        active: true,
        created_by: 1,
        created_at: "2026-07-21T08:00:00"
      }]);
      if (url.endsWith("/api/self-operated-overreceipt-rule-versions")) return jsonResponse([{
        id: 10,
        name: "自营仓超收 5 件",
        allowance: 5,
        active: true,
        created_by: 1,
        created_at: "2026-07-21T08:00:00"
      }]);
      if (url.endsWith("/api/self-operated-inbound-sync/12/preview?limit=100")) {
        return jsonResponse({
          columns: ["入库单号", "入库仓", "SKU", "平台站点", "关联交货单/调拨单", "关联采购单", "应收货"],
          rows: [{
            _row_number: 1,
            入库单号: "IN-1",
            入库仓: "自营仓",
            SKU: "SKU-A",
            平台站点: "AMAZON:SEEKWAY:US",
            "关联交货单/调拨单": "LN-1",
            关联采购单: "PO-1",
            应收货: 10
          }],
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
      if (url.endsWith("/api/self-operated-inbound-sync")) return jsonResponse(inboundSyncStatus);
      if (url.endsWith("/api/batches")) return jsonResponse(batchRows);
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("does not render action buttons before initial data is ready", async () => {
    const fetchMock = vi.mocked(fetch);
    let releaseLoad!: () => void;
    const loadGate = new Promise<void>((resolve) => {
      releaseLoad = resolve;
    });
    vi.stubGlobal("fetch", vi.fn(async (
      input: RequestInfo | URL,
      init: RequestInit = {}
    ) => {
      await loadGate;
      return fetchMock(input, init);
    }));

    render(<BatchesPage onOpen={vi.fn()} />);

    expect(screen.getByLabelText("正在加载交货批次")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新建批次/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /同步采购数据/ })).not.toBeInTheDocument();

    releaseLoad();

    expect(await screen.findByRole("button", { name: /新建批次/ })).toBeEnabled();
    expect(await screen.findByRole("button", { name: /同步采购数据/ })).toBeEnabled();
  });
  it("shows readiness and the next batch action", async () => {
    const onOpen = vi.fn();
    const { container } = render(<BatchesPage onOpen={onOpen} />);

    const status = await screen.findByRole("region", { name: "运行状态" });
    expect(within(status).getByText("基础资料")).toBeInTheDocument();
    expect(within(status).getByText("5 / 5 已就绪")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建批次/ })).toBeEnabled();
    expect(screen.getByLabelText("搜索")).toHaveAttribute("placeholder", "搜索批次名称");
    expect(screen.getByLabelText("状态")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "交货批次列表" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "积加采购数据同步" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /同步采购数据/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "统一批次流程" })).not.toBeInTheDocument();
    expect(screen.getByText("审校待处理")).toBeInTheDocument();
    expect(screen.getByText("2 个文件 · 交货 160")).toBeInTheDocument();
    expect(screen.getAllByText("短尾超收 V1").length).toBeGreaterThan(0);
    expect(container.querySelector(".ant-pagination")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("新建批次"));
    const dialog = await screen.findByRole("dialog", { name: "新建交货批次" });
    const cancel = within(dialog).getByRole("button", { name: /取\s*消/ });
    fireEvent.click(cancel);

    fireEvent.click(screen.getByRole("button", { name: "2026-07-21 交货批次" }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(7));
  });

  it("lets admins select and permanently delete multiple non-active batches", async () => {
    batchRows = [
      batchRows[0],
      {
        ...batchRows[0],
        id: 8,
        name: "第二个可删除批次",
        status: "failed"
      },
      {
        ...batchRows[0],
        id: 9,
        name: "正在计算的批次",
        status: "running"
      }
    ];
    render(<BatchesPage canDeleteBatches onOpen={vi.fn()} />);

    await screen.findByRole("button", { name: "2026-07-21 交货批次" });
    const first = screen.getByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" });
    const second = screen.getByRole("checkbox", { name: "选择批次 第二个可删除批次" });
    const active = screen.getByRole("checkbox", { name: "选择批次 正在计算的批次" });
    expect(active).toBeDisabled();
    expect(second).toBeEnabled();
    fireEvent.click(first);
    await waitFor(() => {
      expect(document.querySelector(".batch-selection-count"))
        .toHaveTextContent("已选 1 项");
    });
    fireEvent.click(
      document.querySelector('tr[data-row-key="8"] input[type="checkbox"]') as HTMLElement
    );
    await waitFor(() => {
      expect(document.querySelector(".batch-selection-count"))
        .toHaveTextContent("已选 2 项");
    });
    expect(document.querySelector('tr[data-row-key="7"]'))
      .toHaveClass("ant-table-row-selected");
    expect(document.querySelector('tr[data-row-key="8"]'))
      .toHaveClass("ant-table-row-selected");

    fireEvent.click(screen.getByRole("button", { name: "删除已选（2）" }));
    expect(await screen.findByText("永久删除选中的 2 个批次？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "永久删除" }));

    await waitFor(() => expect(deleteRequests).toEqual([[7, 8]]));
    await waitFor(() => {
      expect(screen.queryByText("2026-07-21 交货批次")).not.toBeInTheDocument();
      expect(screen.queryByText("第二个可删除批次")).not.toBeInTheDocument();
    });
    expect(screen.getByText("正在计算的批次")).toBeInTheDocument();
  });

  it("shows the independent self-operated inbound workspace", async () => {
    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />);

    await screen.findByRole("heading", { name: "自营仓入库" });
    const status = await screen.findByRole("region", { name: "运行状态" });
    expect(within(status).getByText("4 / 4 已就绪")).toBeInTheDocument();
    expect(within(status).getByText("待入库数据")).toBeInTheDocument();
    expect(screen.getByText("待入库 + 部分入库")).toBeInTheDocument();
    expect(screen.getByText("数据已启用")).toBeInTheDocument();
    expect(screen.queryByText("候选剩余应收总量")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看同步详情" }));
    expect(screen.getByText("候选剩余应收总量")).toBeInTheDocument();
    expect(screen.getByText(/包含 2 条“共享”站点数据/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载提醒清单" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /预览候选数据/ }));
    const preview = await screen.findByRole("dialog", { name: "待入库候选数据预览" });
    expect(within(preview).getByText("IN-1")).toBeInTheDocument();
    expect(within(preview).queryByText("共享站点数据不能自动匹配")).not.toBeInTheDocument();
    fireEvent.click(within(preview).getByRole("button", { name: "Close" }));

    fireEvent.click(screen.getByRole("button", { name: "查看异常数据" }));
    const issues = await screen.findByRole("dialog", { name: "待入库同步异常数据" });
    expect(within(issues).getByText("共享站点数据不能自动匹配")).toBeInTheDocument();
    expect(within(issues).getByRole("columnheader", { name: "入库仓" })).toBeInTheDocument();
    expect(within(issues).getByRole("columnheader", { name: "剩余应收货" })).toBeInTheDocument();
    expect(within(issues).getByRole("columnheader", { name: "关联采购单" })).toBeInTheDocument();
    expect(within(issues).getByText("自营仓")).toBeInTheDocument();
    expect(within(issues).getByText("12")).toBeInTheDocument();
    expect(within(issues).getByRole("button", { name: /下载完整清单/ })).toBeInTheDocument();
    expect(within(issues).queryByText("关联采购单为空")).not.toBeInTheDocument();
    fireEvent.click(within(issues).getByRole("button", { name: "映射错误" }));
    expect(within(issues).getByText("关联采购单为空")).toBeInTheDocument();
    expect(within(issues).queryByText("共享站点数据不能自动匹配")).not.toBeInTheDocument();
    expect(within(issues).queryByText("IN-1")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("当前配置")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /同步待入库数据/ })).toBeInTheDocument();
    expect(screen.getAllByText(/自营仓超收 5 件/).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: "自营仓入库批次列表" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "积加采购数据同步" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "统一批次流程" })).not.toBeInTheDocument();
    expect(screen.queryByText("2026-07-21 交货批次")).not.toBeInTheDocument();
  });

  it("shows an indeterminate progress bar while inbound data is syncing", async () => {
    const job = inboundSyncStatus.job as Record<string, unknown>;
    inboundSyncStatus = {
      ...inboundSyncStatus,
      job: { ...job, status: "running", finished_at: null }
    };

    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />);

    const progress = await screen.findByRole("progressbar", { name: "正在同步待入库数据" });
    expect(progress).toHaveClass("is-indeterminate");
    expect(progress).not.toHaveAttribute("aria-valuenow");
  });

  it("polls only inbound sync status without overlap and fully refreshes once on completion", async () => {
    vi.useFakeTimers();
    const initialFetch = vi.mocked(fetch);
    const requests: string[] = [];
    let statusRequestCount = 0;
    let releaseRunningPoll!: () => void;
    const runningJob = {
      ...(inboundSyncStatus.job as Record<string, unknown>),
      status: "running",
      candidate_version_id: null,
      finished_at: null
    };
    const completedStatus = {
      ...inboundSyncStatus,
      job: {
        ...(inboundSyncStatus.job as Record<string, unknown>),
        status: "succeeded"
      }
    };
    vi.stubGlobal("fetch", vi.fn(async (
      input: RequestInfo | URL,
      init: RequestInit = {}
    ) => {
      const url = String(input);
      requests.push(url.replace(/^.*(?=\/api\/)/, ""));
      if (url.endsWith("/api/self-operated-inbound-sync") && !init.method) {
        statusRequestCount += 1;
        if (statusRequestCount === 1) {
          return jsonResponse({ ...inboundSyncStatus, job: runningJob });
        }
        if (statusRequestCount === 2) {
          return new Promise<Response>((resolve) => {
            releaseRunningPoll = () => resolve(jsonResponse({
              ...inboundSyncStatus,
              job: runningJob
            }));
          });
        }
        return jsonResponse(completedStatus);
      }
      return initialFetch(input, init);
    }));

    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    requests.length = 0;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(requests).toEqual(["/api/self-operated-inbound-sync"]);

    await act(async () => {
      releaseRunningPoll();
      await vi.advanceTimersByTimeAsync(0);
    });
    requests.length = 0;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(requests).toEqual(expect.arrayContaining([
      "/api/self-operated-inbound-sync",
      "/api/batches",
      "/api/input-versions",
      "/api/self-operated-overreceipt-rule-versions"
    ]));
    expect(requests).toHaveLength(4);
  });

  it("creates a self-operated batch with multiple quality delivery files", async () => {
    const onOpen = vi.fn();
    let submittedFiles: FormDataEntryValue[] = [];
    const loadFetch = vi.mocked(fetch);
    vi.stubGlobal("fetch", vi.fn(async (
      input: RequestInfo | URL,
      init: RequestInit = {}
    ) => {
      if (String(input).endsWith("/api/self-operated-batches") && init.method === "POST") {
        const body = init.body as FormData;
        submittedFiles = body.getAll("delivery_file");
        return jsonResponse({ id: 88 });
      }
      return loadFetch(input, init);
    }));

    render(<BatchesPage workflow="self_operated_inbound" onOpen={onOpen} />);

    await screen.findByRole("heading", { name: "自营仓入库" });
    await screen.findByText("4 / 4 已就绪");
    fireEvent.click(screen.getByRole("button", { name: /新建批次/ }));
    const dialog = await screen.findByRole("dialog", { name: "新建自营仓入库批次" });

    expect(within(dialog).getByText("质检交货单")).toBeInTheDocument();
    expect(within(dialog).queryByText("自营仓收货入库单")).not.toBeInTheDocument();
    expect(within(dialog).getByText("锁定待入库数据版本")).toBeInTheDocument();
    expect(within(dialog).getByText("锁定待入库数据版本").closest(".ant-alert"))
      .toHaveClass("self-operated-version-lock", "ant-alert-info");
    expect(within(dialog).getByRole("button", { name: "创建批次" })).toBeDisabled();
    expect(within(dialog).getByText(/本批次将使用：self_operated_inbound-v1/)).toBeInTheDocument();

    const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    expect(input).toHaveAttribute("multiple");
    fireEvent.change(input!, {
      target: {
        files: [
          new File(["first"], "A质检交货单.xlsx"),
          new File(["second"], "B质检交货单.xlsx")
        ]
      }
    });
    await waitFor(() => {
      expect(within(dialog).getByRole("button", { name: "创建批次" })).toBeEnabled();
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建批次" }));

    await waitFor(() => expect(submittedFiles).toHaveLength(2));
    expect(submittedFiles.map((file) => (file as File).name)).toEqual([
      "A质检交货单.xlsx",
      "B质检交货单.xlsx"
    ]);
    expect(onOpen).toHaveBeenCalledWith(88);
  });

  it("requires a delivery file before creating a delivery batch", async () => {
    render(<BatchesPage onOpen={vi.fn()} />);

    await screen.findByText("5 / 5 已就绪");
    fireEvent.click(screen.getByRole("button", { name: /新建批次/ }));
    const dialog = await screen.findByRole("dialog", { name: "新建交货批次" });

    expect(within(dialog).getByText("交货文件")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "创建并上传文件" })).toBeDisabled();
    expect(within(dialog).getByText("至少选择一份；校验通过后创建批次。")).toBeInTheDocument();
  });
});
