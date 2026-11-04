import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DeliveryImportRows from "./DeliveryImportRows";
import { createDetailBatch } from "./detailFixtures";
import { jsonResponse } from "../admin/positionDraftTestSupport";
import type { DeliveryImportRow } from "../../types";

const row: DeliveryImportRow = {
  file_id: 10,
  file_name: "合成文件.xlsx",
  row_index: 0,
  warehouse: "测试仓",
  supplier_code: "GYS-001",
  sku: "SKU-A",
  quantity: 7,
  site: "AMAZON:US",
  document_note: "单据备注一",
  delivery_note: "交货备注一"
};

afterEach(() => vi.unstubAllGlobals());

describe("可导入明细", () => {
  it("渲染只读表格并使用待处理的页大小和分页参数", async () => {
    const fetchRows = vi.fn(async (input: RequestInfo | URL) => {
      const params = new URL(String(input), "http://localhost").searchParams;
      return jsonResponse({
        items: [{ ...row, sku: params.get("offset") === "10" ? "SKU-B" : "SKU-A" }],
        total: 11
      });
    });
    vi.stubGlobal("fetch", fetchRows);
    render(<DeliveryImportRows batch={createDetailBatch()} />);
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    for (const text of ["合成文件.xlsx", "测试仓", "7", "AMAZON:US", "单据备注一", "交货备注一"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByRole("columnheader", { name: "本次交货量" })).toHaveStyle({ textAlign: "right" });
    fireEvent.click(screen.getByTitle("2"));
    expect(await screen.findByText("SKU-B")).toBeInTheDocument();
    expect(fetchRows).toHaveBeenCalledWith(expect.stringContaining("offset=10&limit=10"), expect.anything());
  });

  it("搜索防抖后携带参数并回到第一页，清空后恢复", async () => {
    const fetchRows = vi.fn<typeof fetch>(async () => jsonResponse({ items: [row], total: 11 }));
    vi.stubGlobal("fetch", fetchRows);
    render(<DeliveryImportRows batch={createDetailBatch()} />);
    await screen.findByText("SKU-A");
    fireEvent.click(screen.getByTitle("2"));
    await waitFor(() =>
      expect(fetchRows).toHaveBeenLastCalledWith(expect.stringContaining("offset=10&limit=10"), expect.anything())
    );
    const input = screen.getByLabelText("搜索可导入记录");
    fireEvent.change(input, { target: { value: "sku" } });
    fireEvent.change(input, { target: { value: "sku-a" } });
    expect(fetchRows.mock.calls.some((args) => String(args[0]).includes("search="))).toBe(false);
    await waitFor(() =>
      expect(fetchRows).toHaveBeenLastCalledWith(
        expect.stringContaining("offset=0&limit=10&search=sku-a"),
        expect.anything()
      )
    );
    fireEvent.change(input, { target: { value: "" } });
    await waitFor(() =>
      expect(fetchRows).toHaveBeenLastCalledWith("/api/batches/7/import-rows?offset=0&limit=10", expect.anything())
    );
  });

  it("空结果显示空状态，搜索无结果显示筛选状态", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ items: [], total: 0 }))
    );
    render(<DeliveryImportRows batch={createDetailBatch()} />);
    expect(await screen.findByText("没有可导入记录")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("搜索可导入记录"), { target: { value: "missing" } });
    expect(await screen.findByText("没有匹配的可导入记录")).toBeInTheDocument();
  });

  it("读取失败保留重试入口", async () => {
    const fetchRows = vi
      .fn()
      .mockResolvedValueOnce(new Response("读取失败", { status: 500 }))
      .mockResolvedValue(jsonResponse({ items: [row], total: 1 }));
    vi.stubGlobal("fetch", fetchRows);
    render(<DeliveryImportRows batch={createDetailBatch()} />);
    fireEvent.click(await screen.findByRole("button", { name: "重试" }));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
