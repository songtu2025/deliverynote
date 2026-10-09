import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { fixtureJob } from "./batch-detail/detailFixtures";
import { jsonResponse } from "./admin/positionDraftTestSupport";

describe("BatchDetailWorkbench", () => {
  const { state } = setupBatchDetailTest();

  it.each([
    ["draft", true, false],
    ["preflight_ready", false, true],
    ["queued", false, false],
    ["running", false, false],
    ["failed", true, true],
    ["succeeded", false, false]
  ] as const)("preserves actions in %s", async (status, preflight, compute) => {
    state.batch.status = status;
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText(state.batch.name);
    expect(container.querySelector(".delivery-batch-detail")).toBeInTheDocument();
    const task = screen.getByRole("region", { name: "当前批次任务" });
    expect(within(task).queryByRole("button", { name: /执行预检/ }) !== null).toBe(preflight);
    expect(within(task).queryByRole("button", { name: /启动计算|重新计算/ }) !== null).toBe(compute);
    expect(within(task).queryByRole("button", { name: /上传交货文件/ }) !== null).toBe(preflight || compute);
    expect(within(task).getByRole("region", { name: "批次任务状态" })).toBeInTheDocument();
    expect(within(task).queryByRole("group", { name: "批次处理流程" })).not.toBeInTheDocument();
    if (status !== "succeeded") expect(within(task).getByText("尚未计算")).toBeInTheDocument();
  });

  it("keeps empty-file preflight disabled and upload multiple", async () => {
    state.batch.status = "draft";
    state.batch.files = [];
    state.batch.file_count = 0;
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /执行预检/ })).toBeDisabled();
    expect(container.querySelector('.batch-primary-actions input[type="file"]')).toHaveAttribute("multiple");
    expect(screen.getByText("请先上传一个或多个交货 Excel")).toBeInTheDocument();
  });

  it("leaves the self-operated workbench outside delivery styling", async () => {
    state.batch.workflow = "self_operated_inbound";
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText(state.batch.name);
    expect(container.querySelector(".delivery-batch-detail")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "当前批次任务" })).not.toBeInTheDocument();
    expect(screen.getByText("质检合格总量")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "批次处理流程" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "批次任务状态" })).not.toBeInTheDocument();
  });

  it("keeps locked versions expanded and supports the existing toggle", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const toggle = await screen.findByRole("button", { name: "收起锁定版本" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("purchase-v1")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "查看锁定版本" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("purchase-v1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看锁定版本" }));
    expect(screen.getByText("purchase-v1")).toBeInTheDocument();
  });

  it.each(["上移 KuangBiao-B交货单.xlsx", "下移 KuangBiao-A交货单.xlsx"])(
    "preserves delivery order when using %s",
    async (buttonName) => {
      state.batch.status = "draft";
      const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      await screen.findByText(state.batch.name);
      const fileTable = within(container.querySelector(".file-order-card") as HTMLElement);
      expect(fileTable.getByLabelText("上移 KuangBiao-A交货单.xlsx")).toBeDisabled();
      expect(fileTable.getByLabelText("下移 KuangBiao-B交货单.xlsx")).toBeDisabled();
      fireEvent.click(fileTable.getByLabelText(buttonName));
      await waitFor(() =>
        expect(fetch).toHaveBeenCalledWith(
          "/api/batches/7/files/order",
          expect.objectContaining({ method: "PUT", body: JSON.stringify({ file_ids: [11, 10] }) })
        )
      );
      await screen.findByText("处理顺序已更新，需要重新预检");
    }
  );

  it("does not delete a source file when confirmation is cancelled", async () => {
    state.batch.status = "draft";
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "删除 KuangBiao-A交货单.xlsx" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    expect(screen.getByText("KuangBiao-A交货单.xlsx")).toBeInTheDocument();
  });

  it.each([true, false])("keeps available downloads with pending quantities: %s", async (pending) => {
    state.batch.summary = {
      delivery_total: 160,
      import_total: pending ? 100 : 160,
      manual_total: pending ? 60 : 0,
      conserved: true
    };
    state.batch.download_ready = true;
    state.batch.merged_download_ready = true;
    state.batch.files = state.batch.files.map((file) => ({ ...file, download_ready: true }));
    state.exceptions = pending ? [state.exceptions[0]] : [];
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText(state.batch.name);
    const task = within(screen.getByRole("region", { name: "当前批次任务" }));
    expect(task.getByRole("button", { name: /下载合并结果/ })).toBeEnabled();
    expect(task.getByRole("button", { name: /下载分文件 ZIP/ })).toBeEnabled();
    if (pending) {
      expect(await task.findByText("1 条未完成 · 待处理 60 件")).toBeInTheDocument();
      expect(task.getByText("等待人工审校")).toBeInTheDocument();
      const scroll = vi.fn();
      Object.defineProperty(container.querySelector(".review-section-anchor"), "scrollIntoView", { value: scroll });
      fireEvent.click(task.getByRole("button", { name: "处理异常" }));
      expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
      expect(document.activeElement).toHaveClass("review-section-anchor");
    } else {
      expect(await task.findByText("审校已完成")).toBeInTheDocument();
      expect(task.queryByRole("button", { name: "处理异常" })).not.toBeInTheDocument();
    }
    expect(task.getByText("当前结果文件已生成，可下载")).toBeInTheDocument();
    expect(container.querySelector(".batch-task-spinner")).not.toBeInTheDocument();
  });

  it.each([
    [false, false, false, "生成导出"],
    [true, false, false, "生成合并结果"],
    [false, false, true, "重新生成导出"]
  ] as const)("describes the export generation action %s/%s/%s accurately", async (ready, merged, stale, label) => {
    state.batch.download_ready = ready;
    state.batch.merged_download_ready = merged;
    state.batch.summary = { delivery_total: 160, import_total: 160, manual_total: 0, conserved: true };
    if (stale) state.batch.jobs = { export: fixtureJob({ kind: "export", status: "stale" }) };
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("/export") && init?.method === "POST"
          ? Promise.resolve(jsonResponse(fixtureJob({ kind: "export", status: "queued" })))
          : originalFetch(input, init)
      )
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const button = await screen.findByRole("button", { name: new RegExp(label) });
    expect(
      screen.getByText(
        stale ? "审校已更新，需要重新生成结果" : ready ? "单文件结果已生成，需要生成合并结果" : "需要生成结果"
      )
    ).toBeInTheDocument();
    expect(screen.queryByText("当前结果文件已生成，可下载")).not.toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/batches/7/export", expect.objectContaining({ method: "POST" }))
    );
  });

  it("shows a running export and prevents another generation request", async () => {
    state.batch.jobs = { export: fixtureJob({ kind: "export" }) };
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith("/api/jobs/88")
          ? Promise.resolve(jsonResponse(state.batch.jobs.export))
          : originalFetch(input, init)
      )
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /生成导出/ })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("正在生成结果");
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
});
