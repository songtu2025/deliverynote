import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { fixtureJob } from "./batch-detail/detailFixtures";
import { jsonResponse } from "./admin/positionDraftTestSupport";

describe("BatchDetailWorkbench", () => {
  const { state } = setupBatchDetailTest();

  it("生成失败时主按钮重试生成，原因保留在页头", async () => {
    state.batch.jobs.export = fixtureJob({ kind: "export", status: "failed", error_message: "合成导出错误" });
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("合成导出错误");
    const primary = container.querySelectorAll(".batch-heading .ant-btn-primary");
    expect(primary).toHaveLength(1);
    expect(primary[0]).toHaveTextContent("生成结果");
    expect(screen.queryByRole("button", { name: "开始审校" })).not.toBeInTheDocument();
  });

  it.each([
    ["draft", true, false],
    ["preflight_ready", false, true],
    ["queued", false, false],
    ["running", false, false],
    ["failed", true, false],
    ["succeeded", false, false]
  ] as const)("preserves actions in %s", async (status, preflight, compute) => {
    state.batch.status = status;
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText(state.batch.name);
    expect(container.querySelector(".batch-detail--compact")).toBeInTheDocument();
    const task = screen.getByRole("region", { name: "当前批次任务" });
    expect(within(task).queryByRole("button", { name: /预检并计算/ }) !== null).toBe(preflight);
    expect(within(task).queryByRole("button", { name: /开始计算|重新计算/ }) !== null).toBe(compute);
    expect(within(task).queryByRole("button", { name: /上传交货文件/ })).not.toBeInTheDocument();
    expect(within(task).getByRole("region", { name: "批次任务状态" })).toBeInTheDocument();
    expect(within(task).queryByRole("group", { name: "批次处理流程" })).not.toBeInTheDocument();
    if (status !== "succeeded") expect(within(task).queryByRole("img", { name: /^可导入/ })).not.toBeInTheDocument();
  });

  it("keeps empty-file preflight disabled and upload multiple", async () => {
    state.batch.status = "draft";
    state.batch.files = [];
    state.batch.file_count = 0;
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /预检/ })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "待办 —" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 0" }));
    expect(container.querySelector('.file-order-card input[type="file"]')).toHaveAttribute("multiple");
    expect(screen.getByText("请先上传一个或多个交货 Excel")).toBeInTheDocument();
  });

  it("shares the compact workbench with self-operated batches", async () => {
    state.batch.workflow = "self_operated_inbound";
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByText(state.batch.name);
    expect(container.querySelector(".batch-detail--compact")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "当前批次任务" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "当前批次任务" })).getByText("本次申请")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "批次处理流程" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "批次任务状态" })).toBeInTheDocument();
  });

  it("keeps locked versions expanded and supports the existing toggle", async () => {
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const tab = await screen.findByText("锁定资料", { selector: '[role="tab"]' });
    fireEvent.click(tab);
    const panel = within(screen.getByText("批次锁定版本").closest(".locked-data-card") as HTMLElement);
    const toggle = panel.getByRole("button", { name: "收起锁定版本" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("purchase-v1")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(panel.getByRole("button", { name: "查看锁定版本" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("purchase-v1")).not.toBeInTheDocument();
    fireEvent.click(panel.getByRole("button", { name: "查看锁定版本" }));
    expect(screen.getByText("purchase-v1")).toBeInTheDocument();
  });

  it.each(["上移 KuangBiao-B交货单.xlsx", "下移 KuangBiao-A交货单.xlsx"])(
    "preserves delivery order when using %s",
    async (buttonName) => {
      state.batch.status = "draft";
      const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      await screen.findByText(state.batch.name);
      fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
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
      await screen.findByText("顺序已调整，需要重新预检");
    }
  );

  it("does not delete a source file when confirmation is cancelled", async () => {
    state.batch.status = "draft";
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "来源文件 2" }));
    fireEvent.click(await screen.findByLabelText("删除 KuangBiao-A交货单.xlsx"));
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
    await waitFor(() => expect(task.queryByText("正在读取审校统计…")).not.toBeInTheDocument());
    expect(task.queryByRole("button", { name: /下载合并结果/ }) !== null).toBe(!pending);
    expect(task.queryByRole("button", { name: /下载分文件 ZIP/ })).not.toBeInTheDocument();
    if (pending) {
      expect(await task.findByText("1 条待审校，共 60 件")).toBeInTheDocument();
      expect(task.getByText("1 条待审校，共 60 件")).toBeInTheDocument();
      const scroll = vi.fn();
      Object.defineProperty(container.querySelector(".review-section-anchor"), "scrollIntoView", { value: scroll });
      fireEvent.click(task.getByRole("button", { name: "开始审校" }));
      await waitFor(() => expect(document.activeElement).toHaveClass("review-section-anchor"));
      expect(scroll).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    } else {
      expect(await task.findByText("结果已生成，可以下载")).toBeInTheDocument();
      expect(task.queryByRole("button", { name: "开始审校" })).not.toBeInTheDocument();
    }
    expect(task.getByText("结果可下载")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "来源文件 2" }));
    expect(screen.getByRole("button", { name: /下载分文件 ZIP/ })).toBeEnabled();
    if (pending) expect(screen.getByRole("button", { name: /下载合并结果/ })).toBeEnabled();
    expect(container.querySelector(".batch-task-spinner")).not.toBeInTheDocument();
  });

  it.each([
    [false, false, false, "生成结果"],
    [true, false, false, "生成合并结果"],
    [false, false, true, "重新生成结果"]
  ] as const)("describes the export generation action %s/%s/%s accurately", async (ready, merged, stale, label) => {
    state.exceptions = [];
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
      screen.getByText(stale ? "审校有更新，需重新生成结果" : ready ? "需生成合并结果" : "尚未生成结果")
    ).toBeInTheDocument();
    expect(screen.queryByText("结果可下载")).not.toBeInTheDocument();
    fireEvent.click(button);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/batches/7/export", expect.objectContaining({ method: "POST" }))
    );
  });

  it("shows a running export and prevents another generation request", async () => {
    state.batch.jobs = { export: fixtureJob({ kind: "export" }) };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "生成中" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("正在生成结果");
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it.each(["draft", "preflight_ready", "queued", "running", "succeeded", "failed"])(
    "%s 页头只有一个主按钮且位于操作组末尾",
    async (status) => {
      state.batch.status = status;
      const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
      await screen.findByText(state.batch.name);
      const actions = container.querySelector(".batch-task-actions")!;
      const primary = actions.querySelectorAll(".ant-btn-primary");
      expect(primary).toHaveLength(1);
      expect(Array.from(actions.querySelectorAll("button")).at(-1)).toBe(primary[0]);
      if (["queued", "running"].includes(status)) expect(primary[0]).toBeDisabled();
    }
  );

  it("失败原因紧随状态句，只出现一次且没有独立错误 Alert", async () => {
    state.batch.status = "failed";
    state.batch.error_message = "合成文件缺少 SKU 列";
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("计算失败合成文件缺少 SKU 列");
    expect(screen.getAllByText("合成文件缺少 SKU 列")).toHaveLength(1);
    expect(container.querySelector(".batch-failure-reason")?.parentElement).toBe(status);
    expect(container.querySelector(".batch-stage-error")).toHaveTextContent("失败");
    expect(container.querySelector(".ant-alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/原因见下方/)).not.toBeInTheDocument();
  });

  it("累计实收待核对显示真实阶段和待办，不重复状态提示", async () => {
    state.batch.workflow = "self_operated_inbound";
    state.batch.status = "failed";
    state.batch.error_message = "累计实收核对失败";
    state.batch.receipt = {
      cumulative_total: 20,
      history_total: null,
      requested_total: null,
      issue_count: 1,
      captured_at: "2026-11-04T00:00:00Z"
    };
    state.batch.inbound_file = { uploaded: true, original_name: "合成待入库.xlsx" };
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("tab", { name: "待办 1" })).toHaveAttribute("aria-selected", "true");
    expect(container.querySelector(".batch-stage-review")).toHaveTextContent("待核对");
    expect(screen.getAllByText("1 处累计实收待核对，处理后即可预检")).toHaveLength(1);
    expect(screen.queryByText("累计实收核对失败")).not.toBeInTheDocument();
    expect(container.querySelector(".ant-alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /更多/ }));
    expect(await screen.findByRole("menuitem", { name: "同步积加入库记录" })).not.toHaveAttribute(
      "aria-disabled",
      "true"
    );
    expect(screen.getByRole("button", { name: "累计实收口径" })).toBeInTheDocument();
  });
});
