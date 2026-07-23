import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BatchesPage from "./BatchesPage";

const jsonResponse = (payload: unknown) => new Response(JSON.stringify(payload), {
  status: 200,
  headers: { "Content-Type": "application/json" }
});

describe("BatchesPage", () => {
  beforeEach(() => {
    const versions = ["purchase", "product", "supplier", "position", "template"].map((kind, index) => ({
      id: index + 1,
      kind,
      name: `${kind}-v1`,
      original_name: `${kind}.xlsx`,
      active: true,
      created_by: 1,
      created_at: "2026-07-21T08:00:00"
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/input-versions")) return jsonResponse(versions);
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
      if (url.endsWith("/api/batches")) return jsonResponse([{
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
      }]);
      throw new Error(`Unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows readiness and the next batch action", async () => {
    const onOpen = vi.fn();
    const { container } = render(<BatchesPage onOpen={onOpen} />);

    await screen.findByText("基础资料已就绪");
    expect(screen.getByRole("button", { name: /新建批次/ })).toBeEnabled();
    expect(screen.getByLabelText("搜索")).toHaveAttribute("placeholder", "搜索批次名称");
    expect(screen.getByLabelText("状态")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "交货批次列表" })).toBeInTheDocument();
    expect(screen.getByText("审校待处理")).toBeInTheDocument();
    expect(screen.getByText("2 个文件 · 交货 160")).toBeInTheDocument();
    expect(screen.getByText("新批次将锁定超收规则：短尾超收 V1")).toBeInTheDocument();
    expect(container.querySelector(".ant-pagination")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("新建批次"));
    const dialog = await screen.findByRole("dialog", { name: "新建交货批次" });
    const cancel = within(dialog).getByRole("button", { name: /取\s*消/ });
    fireEvent.click(cancel);

    fireEvent.click(screen.getByRole("button", { name: "2026-07-21 交货批次" }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(7));
  });
});
