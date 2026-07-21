import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BatchDetail from "./BatchDetail";

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { "Content-Type": "application/json" }
});

describe("BatchDetail", () => {
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
    const batch = {
      id: 7,
      name: "2026-07-21 交货批次",
      status: "succeeded",
      created_by: 1,
      version_ids: { purchase: 1, product: 2, supplier: 3, position: 4, template: 5 },
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
    const exceptions = [{
      id: 30,
      batch_file_id: 11,
      sku: "SKU-A",
      original_site: "US",
      full_site: "AMAZON:SEEKWAY:US",
      destination: "水鞋-广州仓",
      delivery_quantity: 80,
      allocated_quantity: 20,
      manual_quantity: 60,
      reason: "超出采购未交量",
      status: "pending",
      parts: []
    }];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/batches/7/exceptions")) return jsonResponse(exceptions);
      if (url.endsWith("/api/batches/7")) return jsonResponse(batch);
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows quantity conservation and prevents an invalid split", async () => {
    render(<BatchDetail batchId={7} onBack={vi.fn()} />);

    await screen.findByText("160 = 100 + 60");
    expect(screen.getByText("序号越小，越先扣减采购余额")).toBeInTheDocument();
    expect(screen.getByText("计算结果").closest(".ant-steps-item")).toHaveClass("ant-steps-item-process");
    fireEvent.click(screen.getByRole("button", { name: "拆分审校" }));

    await screen.findByText("拆分审校 · SKU-A");
    const saveButton = screen.getByRole("button", { name: "保存拆分" });
    expect(saveButton).toBeEnabled();
    const quantity = screen.getByRole("spinbutton", { name: "数量" });
    fireEvent.change(quantity, { target: { value: "59" } });
    await waitFor(() => expect(saveButton).toBeDisabled());
    expect(screen.getByText("1", { selector: ".split-conservation strong" })).toBeInTheDocument();
  }, 30_000);
});
