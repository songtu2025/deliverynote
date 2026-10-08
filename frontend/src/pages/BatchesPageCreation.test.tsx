import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupBatchesPageTests, jsonResponse, FocusTestApp } from "./batchesPageTestSupport";
import BatchesPage from "./BatchesPage";

describe("BatchesPageCreation", () => {
  setupBatchesPageTests();
  it("creates a self-operated batch with multiple quality delivery files", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-08T06:26:35Z"));
    const onOpen = vi.fn();
    let submittedFiles: FormDataEntryValue[] = [];
    const loadFetch = vi.mocked(fetch);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        if (String(input).endsWith("/api/self-operated-batches") && init.method === "POST") {
          const body = init.body as FormData;
          submittedFiles = body.getAll("delivery_file");
          return jsonResponse({ id: 88 });
        }
        return loadFetch(input, init);
      })
    );

    render(<BatchesPage workflow="self_operated_inbound" onOpen={onOpen} />, { wrapper: AntApp });

    await screen.findByRole("heading", { name: "自营仓入库" });
    await screen.findByText("4 / 4 已就绪");
    fireEvent.click(screen.getByRole("button", { name: /新建批次/ }));
    const dialog = await screen.findByRole("dialog", { name: "新建自营仓入库批次" });
    expect(within(dialog).getByRole("textbox", { name: /批次名称/ })).toHaveValue("2026-10-08 自营仓入库批次");

    expect(within(dialog).getByText("质检交货单")).toBeInTheDocument();
    expect(within(dialog).queryByText("自营仓收货入库单")).not.toBeInTheDocument();
    expect(within(dialog).getByText("锁定待入库数据版本")).toBeInTheDocument();
    expect(within(dialog).getByText("锁定待入库数据版本").closest(".ant-alert")).toHaveClass(
      "self-operated-version-lock",
      "ant-alert-info"
    );
    expect(within(dialog).getByRole("button", { name: "创建批次" })).toBeDisabled();
    expect(within(dialog).getByText(/本批次将使用：self_operated_inbound-v1/)).toBeInTheDocument();

    const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    expect(input).toHaveAttribute("multiple");
    fireEvent.change(input!, {
      target: {
        files: [new File(["first"], "A质检交货单.xlsx"), new File(["second"], "B质检交货单.xlsx")]
      }
    });
    await waitFor(() => {
      expect(within(dialog).getByRole("button", { name: "创建批次" })).toBeEnabled();
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建批次" }));

    await waitFor(() => expect(submittedFiles).toHaveLength(2));
    expect(submittedFiles.map((file) => (file as File).name)).toEqual(["A质检交货单.xlsx", "B质检交货单.xlsx"]);
    expect(onOpen).toHaveBeenCalledWith(88);
  });

  it("requires a delivery file before creating a delivery batch", async () => {
    render(<BatchesPage onOpen={vi.fn()} />, { wrapper: AntApp });

    await screen.findByText("5 / 5 已就绪");
    fireEvent.click(screen.getByRole("button", { name: /新建批次/ }));
    const dialog = await screen.findByRole("dialog", { name: "新建交货批次" });

    expect(within(dialog).getByText("交货文件")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "创建并上传文件" })).toBeDisabled();
    expect(within(dialog).getByText("至少选择一份；校验通过后创建批次。")).toBeInTheDocument();
  });
  it("preserves delivery file order when creating a batch", async () => {
    const originalFetch = fetch;
    const onOpen = vi.fn();
    let submittedFiles: FormDataEntryValue[] = [];
    let submittedName: FormDataEntryValue | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/api/batches/with-files") && init?.method === "POST") {
          submittedFiles = (init.body as FormData).getAll("files");
          submittedName = (init.body as FormData).get("name");
          return jsonResponse({ id: 89 });
        }
        return originalFetch(input, init);
      })
    );
    render(<BatchesPage onOpen={onOpen} />, { wrapper: AntApp });
    fireEvent.click(await screen.findByRole("button", { name: /新建批次/ }));
    const dialog = await screen.findByRole("dialog", { name: "新建交货批次" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /批次名称/ }), {
      target: { value: "手工复核批次" }
    });
    const input = dialog.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(input!, { target: { files: [new File(["second"], "B.xlsx"), new File(["first"], "A.xlsx")] } });
    const submit = within(dialog).getByRole("button", { name: "创建并上传文件" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(89));
    expect(submittedFiles.map((file) => (file as File).name)).toEqual(["B.xlsx", "A.xlsx"]);
    expect(submittedName).toBe("手工复核批次");
  });
  it("regenerates a Beijing timestamp including seconds on each open across midnight", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-08T15:59:58Z"));
    render(<BatchesPage onOpen={vi.fn()} />, { wrapper: FocusTestApp });
    fireEvent.click(await screen.findByRole("button", { name: /新建批次/ }));
    const first = await screen.findByRole("dialog", { name: "新建交货批次" });
    expect(within(first).getByRole("textbox", { name: /批次名称/ })).toHaveValue("2026-10-08 交货批次 23:59:58");
    fireEvent.click(within(first).getByRole("button", { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    vi.setSystemTime(new Date("2026-10-08T16:00:03Z"));
    fireEvent.click(screen.getByRole("button", { name: /新建批次/ }));
    const second = await screen.findByRole("dialog", { name: "新建交货批次" });
    expect(within(second).getByRole("textbox", { name: /批次名称/ })).toHaveValue("2026-10-09 交货批次 00:00:03");
  });
  it("keeps batch name labels associated after both workflow dialogs have been opened", async () => {
    render(
      <>
        <section aria-label="交货测试">
          <BatchesPage onOpen={vi.fn()} />
        </section>
        <section aria-label="自营仓测试">
          <BatchesPage workflow="self_operated_inbound" onOpen={vi.fn()} />
        </section>
      </>,
      { wrapper: FocusTestApp }
    );
    const delivery = within(screen.getByRole("region", { name: "交货测试" }));
    const inbound = within(screen.getByRole("region", { name: "自营仓测试" }));
    fireEvent.click(await delivery.findByRole("button", { name: /新建批次/ }));
    const firstDialog = await screen.findByRole("dialog", { name: "新建交货批次" });
    expect(within(firstDialog).getByRole("textbox", { name: /批次名称/ })).toBeInTheDocument();
    fireEvent.click(within(firstDialog).getByRole("button", { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "新建交货批次" })).not.toBeInTheDocument());
    fireEvent.click(await inbound.findByRole("button", { name: /新建批次/ }));
    const secondDialog = await screen.findByRole("dialog");
    expect(within(secondDialog).getByText("新建自营仓入库批次")).toBeInTheDocument();
    expect(within(secondDialog).getByRole("textbox", { name: /批次名称/ })).toBeInTheDocument();
  });
});
