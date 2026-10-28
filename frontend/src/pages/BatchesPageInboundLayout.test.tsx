import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FocusTestApp, jsonResponse, setupBatchesPageTests } from "./batchesPageTestSupport";
import BatchesPage from "./BatchesPage";

describe("自营仓紧凑列表", () => {
  const state = setupBatchesPageTests();
  beforeEach(() => {
    Object.assign(state.batchRows[0], {
      workflow: "self_operated_inbound",
      name: "自营仓合成批次",
      inbound_file: { uploaded: true, original_name: "锁定待入库版本 V1" }
    });
  });

  it("shows batch identity, inbound source and quantities with self-operated labels", async () => {
    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: FocusTestApp });
    const table = await screen.findByRole("table", { name: "自营仓入库批次列表" });
    const row = within(table).getByRole("button", { name: "自营仓合成批次" }).closest("tr")!;

    expect(table.closest(".batch-list-page")).toHaveClass("batch-list-page--compact");
    expect(within(row).getByText(/批次 #7/)).toHaveTextContent("待入库数据已就绪");
    expect(within(row).getByTitle("锁定待入库版本 V1")).toBeInTheDocument();
    expect(within(row).getByText(/2 份质检单/)).toHaveTextContent("质检合格 160");
    expect(within(row).getByText(/可入库 100/)).toHaveTextContent("待处理 60");
    expect(within(row).queryByText(/可导入|交货 160/)).not.toBeInTheDocument();
    expect(within(row).getByText("审校待处理")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /删除批次/ })).not.toBeInTheDocument();
  });

  it.each([true, false])("distinguishes computed zero quantities from missing results: %s", async (computed) => {
    Object.assign(state.batchRows[0], {
      summary: computed ? { delivery_total: 0, import_total: 0, manual_total: 0, conserved: true } : undefined,
      inbound_file: { uploaded: false, original_name: "" }
    });
    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: FocusTestApp });
    const row = (await screen.findByRole("button", { name: "自营仓合成批次" })).closest("tr")!;

    expect(within(row).getByText(/批次 #7/)).toHaveTextContent("待入库数据未就绪");
    if (computed) {
      expect(within(row).getByText(/质检合格 0/)).toBeInTheDocument();
      expect(within(row).getByText(/可入库 0/)).toHaveTextContent("待处理 0");
      expect(within(row).queryByText("尚未计算")).not.toBeInTheDocument();
    } else {
      expect(within(row).getByText("尚未计算")).toBeInTheDocument();
      expect(within(row).queryByText(/可入库 0/)).not.toBeInTheDocument();
    }
  });

  it("keeps creation disabled when the inbound API version is missing", async () => {
    const original = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const response = await original(input, init);
        if (!String(input).endsWith("/api/input-versions")) return response;
        const versions = (await response.json()) as Array<{ kind: string }>;
        return jsonResponse(versions.filter((version) => version.kind !== "self_operated_inbound"));
      })
    );
    render(<BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />, { wrapper: FocusTestApp });

    expect(await screen.findByText("3 / 4 待补齐")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建批次/ })).toBeDisabled();
  });
});
