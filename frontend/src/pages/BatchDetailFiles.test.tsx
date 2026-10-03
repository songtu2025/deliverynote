import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";

describe("BatchDetailFiles", () => {
  const { state } = setupBatchDetailTest();

  it("offers merged and per-file downloads without a duplicate export card", async () => {
    state.batch.download_ready = true;
    state.batch.merged_download_ready = true;
    state.batch.files = state.batch.files.map((file) => ({
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

    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    const mergedButton = await screen.findByRole("button", { name: /下载合并结果/ });
    const zipButton = screen.getByRole("button", { name: /下载分文件 ZIP/ });
    expect(screen.getAllByRole("button", { name: "下载单文件结果" })).toHaveLength(2);
    expect(container.querySelector(".export-card")).not.toBeInTheDocument();

    fireEvent.click(mergedButton);
    fireEvent.click(zipButton);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/batches/7/download-merged", expect.any(Object));
      expect(fetch).toHaveBeenCalledWith("/api/batches/7/download", expect.any(Object));
    });
  }, 30_000);

  it("shows a download error when the file request fails", async () => {
    state.batch.download_ready = true;
    state.batch.file_count = 1;
    state.batch.files = [{ ...state.batch.files[0], download_ready: true }];
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("/api/batch-files/10/download")
          ? Promise.resolve(new Response("unavailable", { status: 503 }))
          : originalFetch(input, init)
      )
    );

    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /下载处理结果/ }));

    await screen.findByText("下载失败");
  });

  it("allows multiple self-operated delivery files to be reordered", async () => {
    state.batch = {
      ...state.batch,
      workflow: "self_operated_inbound",
      name: "2026-08-21 自营仓入库批次",
      status: "draft",
      inbound_file: {
        original_name: "自营仓收货入库单.xlsx",
        uploaded: true
      },
      summary: {
        delivery_total: 0,
        import_total: 0,
        manual_total: 0,
        conserved: true
      }
    };
    state.exceptions = [];

    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByText("2 份质检单 + 1 份待入库数据")).toBeInTheDocument();
    expect(screen.getByText("序号越小，越先扣减待入库余额和超收额度")).toBeInTheDocument();
    const uploadInput = container.querySelector<HTMLInputElement>('.batch-primary-actions input[type="file"]');
    expect(uploadInput).toHaveAttribute("multiple");
    fireEvent.click(screen.getByRole("button", { name: "下移 KuangBiao-A交货单.xlsx" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/batches/7/files/order",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ file_ids: [11, 10] })
        })
      );
    });
    expect(await screen.findByText("处理顺序已更新，需要重新预检")).toBeInTheDocument();
  });
});
