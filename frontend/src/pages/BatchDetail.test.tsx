import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BatchDetail from "./BatchDetail";

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { "Content-Type": "application/json" }
});

describe("BatchDetail", () => {
  let batchPayload: Record<string, any>;

  beforeEach(() => {
    const version = (id: number, kind: string) => ({
      id,
      kind,
      name: `${kind}-v1`,
      original_name: `${kind}.xlsx`,
      active: true,
      created_by: 1,
      created_at: "2026-07-21T08:00:00"
    });
    batchPayload = {
      id: 7,
      name: "2026-07-21 交货批次",
      status: "succeeded",
      created_by: 1,
      version_ids: { purchase: 1, product: 2, supplier: 3, position: 4, template: 5 },
      overreceipt_rule: {
        id: 9,
        name: "短尾超收 V1",
        short_tail_limit: 50,
        medium_tail_limit: 20,
        long_tail_limit: 10,
        allowed_warehouses: ["水鞋-广州仓"],
        active: false,
        created_by: 1,
        created_at: "2026-07-21T07:00:00"
      },
      versions: {
        purchase: version(1, "purchase"),
        product: version(2, "product"),
        supplier: version(3, "supplier"),
        position: version(4, "position"),
        template: version(5, "template")
      },
      jobs: {},
      error_message: null,
      download_ready: false,
      merged_download_ready: false,
      created_at: "2026-07-21T08:00:00",
      updated_at: "2026-07-21T09:00:00",
      file_count: 2,
      summary: { delivery_total: 160, import_total: 100, manual_total: 60, conserved: true },
      files: [
        {
          id: 10,
          batch_id: 7,
          original_name: "KuangBiao-A交货单.xlsx",
          file_order: 1,
          supplier_name: "KuangBiao",
          supplier_code: "GYS-023",
          document_note: "A",
          delivery_total: 80,
          import_total: 80,
          manual_total: 0,
          download_ready: false
        },
        {
          id: 11,
          batch_id: 7,
          original_name: "KuangBiao-B交货单.xlsx",
          file_order: 2,
          supplier_name: "KuangBiao",
          supplier_code: "GYS-023",
          document_note: "B",
          delivery_total: 80,
          import_total: 20,
          manual_total: 60,
          download_ready: false
        }
      ]
    };
    const exceptions = [
      {
        id: 30,
        batch_file_id: 11,
        sku: "SKU-A",
        original_site: "US",
        full_site: "AMAZON:SEEKWAY:US",
        destination: "水鞋-东莞仓",
        delivery_quantity: 80,
        allocated_quantity: 20,
        purchase_allocated_quantity: 20,
        overreceipt_allocated_quantity: 0,
        overreceipt_remaining_quantity: null,
        manual_quantity: 60,
        reason: "超出采购未交量",
        status: "pending",
        scale_position: "短尾",
        stocking_position: "备货",
        ordered_days: 90,
        parts: []
      },
      {
        id: 31,
        batch_file_id: 11,
        sku: "SKU-B",
        original_site: "CA",
        full_site: "AMAZON:SEEKWAY:CA",
        destination: "水鞋-东莞仓",
        delivery_quantity: 20,
        allocated_quantity: 0,
        purchase_allocated_quantity: 0,
        overreceipt_allocated_quantity: 0,
        overreceipt_remaining_quantity: null,
        manual_quantity: 20,
        reason: "未找到可交货采购需求",
        status: "pending",
        scale_position: "中尾",
        stocking_position: "不备货",
        ordered_days: 60,
        parts: []
      },
      {
        id: 32,
        batch_file_id: 11,
        sku: "SKU-C",
        original_site: "US",
        full_site: "AMAZON:OTHER:US、AMAZON:SEEKWAY:US",
        destination: "",
        delivery_quantity: 12,
        allocated_quantity: 0,
        purchase_allocated_quantity: 0,
        overreceipt_allocated_quantity: 0,
        overreceipt_remaining_quantity: null,
        manual_quantity: 12,
        reason: "产品信息站点不唯一",
        status: "pending",
        scale_position: "",
        stocking_position: "",
        ordered_days: "",
        parts: []
      },
      {
        id: 33,
        batch_file_id: 11,
        sku: "SKU-D",
        original_site: "US",
        full_site: "AMAZON:SEEKWAY:US",
        destination: "水鞋-广州仓",
        delivery_quantity: 85,
        allocated_quantity: 70,
        purchase_allocated_quantity: 20,
        overreceipt_allocated_quantity: 50,
        overreceipt_remaining_quantity: 0,
        manual_quantity: 15,
        reason: "超出允许超收量",
        status: "pending",
        scale_position: "短尾",
        stocking_position: "备货",
        ordered_days: 90,
        parts: []
      }
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/batches/7/exceptions")) return jsonResponse(exceptions);
      if (url.endsWith("/api/batches/7")) return jsonResponse(batchPayload);
      if (url.endsWith("/api/batches/7/download-merged")) {
        return new Response("merged", { status: 200 });
      }
      if (url.endsWith("/api/batches/7/download")) {
        return new Response("zip", { status: 200 });
      }
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows quantity conservation and prevents an invalid split", async () => {
    render(<BatchDetail batchId={7} onBack={vi.fn()} />);

    await screen.findByText("160 = 100 + 60");
    expect(screen.getByText("序号越小，越先扣减采购余额")).toBeInTheDocument();
    expect(screen.getByText("异常审校").closest(".ant-steps-item")).toHaveClass("ant-steps-item-process");
    expect(screen.getByText("当前阶段：异常审校")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看并处理（60）" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "规模定位" })).toBeInTheDocument();
    expect(screen.getAllByText("短尾").length).toBeGreaterThan(0);
    expect(screen.getByText("短尾超收 V1")).toBeInTheDocument();
    expect(screen.getByText("短尾 +50 / 中尾 +20 / 长尾 +10")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "查看并处理" })[0]);

    await screen.findByText("拆分审校 · SKU-A");
    const drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("规模定位")).toBeInTheDocument();
    expect(within(drawer).getByText("短尾")).toBeInTheDocument();
    expect(within(drawer).getByText("备货定位")).toBeInTheDocument();
    expect(within(drawer).getByText("备货")).toBeInTheDocument();
    expect(within(drawer).getByText("已下单可售天数")).toBeInTheDocument();
    expect(within(drawer).getByText("90")).toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: "保存拆分" });
    expect(saveButton).toBeEnabled();
    const quantity = screen.getByRole("spinbutton", { name: "数量" });
    fireEvent.change(quantity, { target: { value: "59" } });
    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(screen.getByText("1", { selector: ".split-conservation strong" })).toBeInTheDocument();
  }, 30_000);

  it("filters pending rows by site, scale position, and stocking position", async () => {
    render(<BatchDetail batchId={7} onBack={vi.fn()} />);

    await screen.findByText("SKU-A");
    expect(screen.getByText("SKU-B")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "原因筛选" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "状态筛选" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "站点筛选" }));
    fireEvent.click(await screen.findByText("AMAZON:SEEKWAY:US", { selector: ".ant-select-item-option-content" }));
    await waitFor(() => expect(screen.queryByText("SKU-B")).not.toBeInTheDocument());

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "规模定位筛选" }));
    fireEvent.click(await screen.findByText("短尾", { selector: ".ant-select-item-option-content" }));
    expect(screen.getByText("SKU-A")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "备货定位筛选" }));
    fireEvent.click(await screen.findByText("备货", { selector: ".ant-select-item-option-content" }));
    expect(screen.getByText("SKU-A")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByRole("combobox", { name: "规模定位筛选" }));
    fireEvent.click(await screen.findByText("中尾", { selector: ".ant-select-item-option-content" }));
    await screen.findByText("没有匹配的待处理记录");
  }, 30_000);

  it("offers merged and per-file downloads without a duplicate export card", async () => {
    batchPayload.download_ready = true;
    batchPayload.merged_download_ready = true;
    batchPayload.files = batchPayload.files.map((file: Record<string, unknown>) => ({
      ...file,
      download_ready: true
    }));
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:test")
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn()
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    const { container } = render(<BatchDetail batchId={7} onBack={vi.fn()} />);

    const mergedButton = await screen.findByRole("button", { name: /下载合并结果/ });
    const zipButton = screen.getByRole("button", { name: /下载分文件 ZIP/ });
    expect(container.querySelector(".export-card")).not.toBeInTheDocument();

    fireEvent.click(mergedButton);
    fireEvent.click(zipButton);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/batches/7/download-merged",
        expect.any(Object)
      );
      expect(fetch).toHaveBeenCalledWith(
        "/api/batches/7/download",
        expect.any(Object)
      );
    });
  }, 30_000);

  it("shows reason-specific review guidance and uses candidate sites as choices", async () => {
    render(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByRole("columnheader", { name: "审校依据" })).toBeInTheDocument();

    const excessRow = (await screen.findByText("SKU-A")).closest("tr");
    expect(excessRow).not.toBeNull();
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("已分配 20");
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("超出 60");
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("未命中超收规则");
    fireEvent.click(within(excessRow!).getByRole("button", { name: "查看并处理" }));
    let drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("采购量与超出量")).toBeInTheDocument();
    expect(within(drawer).getByText("已分配量")).toBeInTheDocument();
    expect(within(drawer).getByText("超出量")).toBeInTheDocument();
    expect(within(drawer).getByText("未命中本批次超收规则")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const noPurchaseRow = screen.getByText("SKU-B").closest("tr");
    expect(noPurchaseRow).not.toBeNull();
    expect(noPurchaseRow!.querySelector(".exception-evidence-cell")).toHaveTextContent(
      "需核对 供应商、SKU、站点、目的仓"
    );
    fireEvent.click(within(noPurchaseRow!).getByRole("button", { name: "查看并处理" }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("核对锁定采购版本")).toBeInTheDocument();
    expect(within(drawer).getByText(/供应商、SKU、站点和目的仓/)).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const ambiguousRow = screen.getByText("SKU-C").closest("tr");
    expect(ambiguousRow).not.toBeNull();
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("候选站点");
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("AMAZON:OTHER:US");
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("AMAZON:SEEKWAY:US");
    fireEvent.click(within(ambiguousRow!).getByRole("button", { name: "查看并处理" }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("选择候选站点")).toBeInTheDocument();
    const siteChoice = within(drawer).getByRole("radio", { name: "AMAZON:SEEKWAY:US" });
    fireEvent.click(siteChoice);
    expect(siteChoice).toBeChecked();
    expect(within(drawer).queryByRole("textbox", { name: "完整站点" })).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const allowanceRow = screen.getByText("SKU-D").closest("tr");
    expect(allowanceRow).not.toBeNull();
    expect(allowanceRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("正常采购 20");
    expect(allowanceRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("使用超收 50");
    expect(allowanceRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("剩余 0");
    fireEvent.click(within(allowanceRow!).getByRole("button", { name: "查看并处理" }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("超收额度使用情况")).toBeInTheDocument();
    expect(within(drawer).getByText("正常采购分配")).toBeInTheDocument();
    expect(within(drawer).getByText("本条使用超收额度")).toBeInTheDocument();
    expect(within(drawer).getByText("剩余额度")).toBeInTheDocument();
    const guidance = within(drawer).getByRole("region", { name: "原因指导" });
    expect(within(guidance).getByText("20")).toBeInTheDocument();
    expect(within(guidance).getByText("50")).toBeInTheDocument();
    expect(within(guidance).getByText("0")).toBeInTheDocument();
  }, 30_000);
});
