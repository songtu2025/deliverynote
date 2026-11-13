import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App, ConfigProvider } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PurchaseEntryPage from "./PurchaseEntryPage";
import type { PurchaseEntryPreview } from "../purchaseEntryApi";

const preview = {
  supplier_code: "GYS001",
  order_prefix: "CG001",
  row_count: 2,
  batch_count: 1,
  total_quantity: "25",
  skipped_zero_count: 1,
  batches: [
    { order_number: "CG00101", source_site: "US", delivery_date: "2026-12-01", row_count: 2, total_quantity: "25" }
  ],
  preview: [
    {
      order_number: "CG00101",
      sku: "SKU-A",
      site: "SEEKWAY:US",
      msku: "MSKU-A",
      warehouse: "采购仓",
      quantity: "25",
      unit_price: "10.50",
      delivery_date: "2026-12-01",
      note: "合成备注"
    }
  ],
  versions: { supplier: 1, product: 2, sku_warehouse: 3, purchase_template: 4 }
} satisfies PurchaseEntryPreview;

function mountPage() {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <PurchaseEntryPage />
      </App>
    </ConfigProvider>
  );
}

async function chooseFile(container: HTMLElement, name = "采购单.xlsx") {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(["synthetic"], name)] } });
  await waitFor(() => expect(screen.getByText(name)).toBeInTheDocument());
}

async function validateFile(container: HTMLElement) {
  await chooseFile(container);
  fireEvent.click(screen.getByRole("button", { name: "校验预览" }));
  await screen.findByText("CG00101");
}

describe("采购单录入", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:purchase"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/preview")) return new Response(JSON.stringify(preview));
        return new Response("xlsx");
      })
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("上传单个 xlsx 后预览批次汇总和数量", async () => {
    const { container } = mountPage();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(input).toHaveAttribute("accept", ".xlsx");
    expect(input.multiple).toBe(false);
    expect(screen.getByRole("button", { name: "校验预览" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载合并 Excel" })).toBeDisabled();
    await validateFile(container);
    const [path, init] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe("/api/purchase-entry/preview");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect((init?.body as FormData).get("file")).toBeInstanceOf(File);
    expect(screen.getByRole("columnheader", { name: "自定义采购单号" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "来源站点" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "合同交期" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "明细数" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "采购量" })).toBeInTheDocument();
    expect(screen.queryByText(/版本 ID/)).not.toBeInTheDocument();
  });

  it.each([
    ["下载合并 Excel", "merged"],
    ["下载分批 ZIP", "split"]
  ])("%s 使用预览锁定的资料版本", async (label, mode) => {
    const { container } = mountPage();
    await validateFile(container);
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce());
    const [path, init] = vi.mocked(fetch).mock.calls[1];
    expect(path).toBe("/api/purchase-entry/export");
    expect(init?.method).toBe("POST");
    const body = init?.body as FormData;
    expect(body.get("mode")).toBe(mode);
    expect(body.get("version_ids")).toBe(JSON.stringify(preview.versions));
    expect(body.get("file")).toBeInstanceOf(File);
  });

  it("更换文件立即失效预览并禁止下载", async () => {
    const { container } = mountPage();
    await validateFile(container);
    await chooseFile(container, "另一个采购单.xlsx");
    expect(screen.queryByText("CG00101")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载合并 Excel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载分批 ZIP" })).toBeDisabled();
  });

  it("拒绝旧格式并保留文件供替换", async () => {
    const { container } = mountPage();
    await chooseFile(container, "采购单.xls");
    fireEvent.click(screen.getByRole("button", { name: "校验预览" }));
    expect(await screen.findByText("采购单仅支持 .xlsx 文件")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("预览失败保留错误和文件，重试后可继续下载", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "商品信息缺少国家列" }), { status: 400 })
    );
    const { container } = mountPage();
    await chooseFile(container);
    fireEvent.click(screen.getByRole("button", { name: "校验预览" }));
    expect(await screen.findByText("商品信息缺少国家列")).toBeInTheDocument();
    expect(screen.getByText("采购单.xlsx")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "校验预览" }));
    await screen.findByText("CG00101");
    expect(screen.queryByText("商品信息缺少国家列")).not.toBeInTheDocument();
  });

  it("导出期间冻结操作，失败后保留预览并可重试", async () => {
    const { container } = mountPage();
    await validateFile(container);
    let finish: (response: Response) => void = () => undefined;
    vi.mocked(fetch).mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        })
    );
    fireEvent.click(screen.getByRole("button", { name: "下载分批 ZIP" }));
    expect(container.querySelector('input[type="file"]')).toBeDisabled();
    expect(screen.getByRole("button", { name: "校验预览" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载合并 Excel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载分批 ZIP" })).toHaveAttribute("aria-busy", "true");
    await act(async () => finish(new Response(JSON.stringify({ detail: "生成采购单失败，请重试" }), { status: 500 })));
    await screen.findByText("生成采购单失败，请重试");
    expect(screen.getByText("CG00101")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载分批 ZIP" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "下载分批 ZIP" }));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce());
  });
});
