import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { jsonResponse } from "./admin/positionDraftTestSupport";

describe("BatchDetailFiles", () => {
  const { state } = setupBatchDetailTest();

  function acceptUpload(path: string) {
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith(path) && init?.method === "POST"
          ? Promise.resolve(jsonResponse(state.batch))
          : originalFetch(input, init)
      )
    );
  }

  it("offers merged and per-file downloads without a duplicate export card", async () => {
    state.exceptions = [];
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
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
    const zipButton = screen.getByRole("button", { name: /下载分文件 ZIP/ });
    expect(
      within(container.querySelector(".file-order-card") as HTMLElement).getAllByRole("button", {
        name: "下载单文件结果",
        hidden: true
      })
    ).toHaveLength(2);
    expect(container.querySelector(".export-card")).not.toBeInTheDocument();

    fireEvent.click(mergedButton);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/batches/7/download-merged", expect.any(Object)));
    // 一次只下载一个文件：前一个下载结束后才能点下一个。
    await waitFor(() => expect(zipButton).toBeEnabled());
    fireEvent.click(zipButton);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/batches/7/download", expect.any(Object)));
  }, 30_000);

  it("shows a download error when the file request fails", async () => {
    state.exceptions = [];
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
    fireEvent.click(await screen.findByRole("button", { name: /下载结果/ }));

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

    expect(await screen.findByText("2 份质检交货单已上传，确认顺序后预检并计算")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
    fireEvent.focus(screen.getByRole("button", { name: "文件顺序说明" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("序号越小，越先扣减待入库余额和超收额度");
    const uploadInput = container.querySelector<HTMLInputElement>('.file-order-card input[type="file"]');
    expect(uploadInput).toHaveAttribute("multiple");
    const fileTable = within(container.querySelector(".file-order-card") as HTMLElement);
    fireEvent.click(fileTable.getByLabelText("下移 KuangBiao-A交货单.xlsx"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/batches/7/files/order",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ file_ids: [11, 10] })
        })
      );
    });
    expect(await screen.findByText("顺序已调整，需要重新预检")).toBeInTheDocument();
  });

  it.each(["delivery", "self_operated_inbound"] as const)(
    "%s 在来源文件中补传，页头不显示上传按钮",
    async (workflow) => {
      state.batch.workflow = workflow;
      state.batch.status = "draft";
      state.batch.inbound_file = { uploaded: true, original_name: "合成.xlsx" };
      acceptUpload("/api/batches/7/files");
      const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      const header = within(await screen.findByRole("region", { name: "批次任务状态" }));
      expect(header.queryByRole("button", { name: /上传|添加/ })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
      expect(
        screen.getByRole("button", { name: workflow === "delivery" ? "添加交货文件" : "添加质检交货单" })
      ).toBeEnabled();
      const input = container.querySelector<HTMLInputElement>('.file-order-card input[type="file"]')!;
      fireEvent.change(input, { target: { files: [new File(["synthetic"], "合成交货.xlsx")] } });
      await waitFor(() =>
        expect(fetch).toHaveBeenCalledWith(
          "/api/batches/7/files",
          expect.objectContaining({ method: "POST", body: expect.any(FormData) })
        )
      );
    }
  );

  it.each([false, true])("改用本地入库单确认后才选文件，确认：%s", async (confirm) => {
    state.batch.workflow = "self_operated_inbound";
    state.batch.status = "draft";
    state.batch.inbound_file = { uploaded: true, original_name: "合成.xlsx" };
    acceptUpload("/api/self-operated-batches/7/inbound-file");
    const picker = vi.spyOn(HTMLInputElement.prototype, "click");
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /更多/ }));
    expect(screen.queryByRole("menuitem", { name: "同步积加入库记录" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("menuitem", { name: "改用本地入库单" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText("将停止从积加实时取数，以上传文件为准，并作废当前核对与计算结果。")).toBeInTheDocument();
    expect(picker).not.toHaveBeenCalled();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    fireEvent.click(dialog.getByRole("button", { name: confirm ? "选择本地入库单" : /取\s*消/ }));
    if (!confirm) {
      expect(picker).not.toHaveBeenCalled();
      return;
    }
    await waitFor(() => expect(picker).toHaveBeenCalledOnce());
    const input = container.querySelector<HTMLInputElement>('.batch-task-actions input[type="file"]')!;
    fireEvent.change(input, { target: { files: [new File(["synthetic"], "合成入库.xlsx")] } });
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/self-operated-batches/7/inbound-file",
        expect.objectContaining({ method: "POST", body: expect.any(FormData) })
      )
    );
  });

  it.each(["delivery", "self_operated_inbound"] as const)("%s 禁用预检可用键盘聚焦查看原因", async (workflow) => {
    state.batch.workflow = workflow;
    state.batch.status = "draft";
    state.batch.files = [];
    state.batch.file_count = 0;
    state.batch.inbound_file = { uploaded: true, original_name: "合成.xlsx" };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const button = await screen.findByRole("button", { name: "预检并计算" });
    expect(button).toBeDisabled();
    expect(button.parentElement).toHaveAttribute("tabindex", "0");
    button.parentElement!.focus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      workflow === "delivery" ? "请先上传交货文件" : "请先上传质检交货单"
    );
    expect(document.activeElement).toBe(button.parentElement);
  });

  it("交货批次有待审校时仍可从来源文件生成结果，页头只有审校主操作", async () => {
    acceptUpload("/api/batches/7/export");
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const header = within(await screen.findByRole("region", { name: "批次任务状态" }));
    expect(await header.findByText("4 条待审校，共 107 件")).toBeInTheDocument();
    expect(header.getByRole("button", { name: "开始审校" })).toBeEnabled();
    expect(header.queryByRole("button", { name: /生成结果/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
    const generate = screen.getByRole("button", { name: "生成结果" });
    expect(generate).toBeEnabled();
    fireEvent.click(generate);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/batches/7/export", expect.objectContaining({ method: "POST" }))
    );
  });
});
