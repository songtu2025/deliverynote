import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { createDetailExceptions, fixtureJob, fixtureVersion } from "./batch-detail/detailFixtures";
import { deferred, jsonResponse } from "./admin/positionDraftTestSupport";

describe("自营仓批次详情", () => {
  const { state } = setupBatchDetailTest();
  beforeEach(() => {
    Object.assign(state.batch, {
      workflow: "self_operated_inbound",
      receipt: { cumulative_total: 163, history_total: 3, requested_total: 160, issue_count: 0 },
      name: "合成自营仓详情",
      version_ids: { product: 2, supplier: 3, inbound_template: 6, self_operated_inbound: 7 },
      versions: {
        product: fixtureVersion(2, "product"),
        supplier: fixtureVersion(3, "supplier"),
        inbound_template: fixtureVersion(6, "inbound_template"),
        self_operated_inbound: fixtureVersion(7, "self_operated_inbound")
      },
      inbound_file: { uploaded: true, original_name: "合成待入库来源.xlsx" }
    });
    state.exceptions = [
      {
        ...state.exceptions[2],
        delivery_quantity: 60,
        manual_quantity: 60,
        allowed_actions: []
      }
    ];
  });

  it("复用紧凑任务区，展示自营仓数量口径和适用的审校字段", async () => {
    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "当前批次任务" }));
    expect(container.querySelector(".batch-detail--compact")).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "待办 1" })).toBeInTheDocument();
    expect(task.getByText("本次申请")).toBeInTheDocument();
    expect(task.getByLabelText("入库数量摘要")).toHaveTextContent("累计实收 163 − 历史已入库 3 = 本次申请 160");
    expect(screen.queryByRole("group", { name: "批次处理流程" })).not.toBeInTheDocument();
    const page = within(container);
    expect(page.queryByLabelText("规模定位筛选")).not.toBeInTheDocument();
    expect(page.queryByLabelText("备货定位筛选")).not.toBeInTheDocument();
    expect(page.queryByRole("columnheader", { name: "规模定位" })).not.toBeInTheDocument();
    expect(page.queryByText("查看并处理")).not.toBeInTheDocument();
    fireEvent.click(page.getByRole("button", { name: state.exceptions[0].sku }));
    const drawer = within(await screen.findByRole("dialog"));
    expect(drawer.getByText("处理依据 · " + state.exceptions[0].sku)).toBeVisible();
    expect(drawer.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(drawer.queryByRole("button", { name: /保存|追加|线下处理/ })).not.toBeInTheDocument();
    expect(page.queryByText("保存并重新计算")).not.toBeInTheDocument();
  });

  it.each([
    ["compute", "queued", "排队中"],
    ["compute", "running", "正在计算"],
    ["export", "queued", "排队中"],
    ["export", "running", "正在生成结果"]
  ] as const)("恢复真实任务状态 %s/%s", async (kind, status, title) => {
    state.batch.jobs = { [kind]: fixtureJob({ kind, status }) };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent(title);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("翻页和搜索显示指定超收入口，勾选后显示收尾操作", async () => {
    const base = createDetailExceptions()[3];
    state.exceptions = Array.from({ length: 12 }, (_, index) => ({
      ...base,
      id: 100 + index,
      sku: "SKU-" + (index + 1)
    }));
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findAllByRole("button", { name: "指定超收" })).toHaveLength(10);
    expect(screen.queryByRole("spinbutton", { name: "本批追加" })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTitle("2")[0]);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "指定超收" })).toHaveLength(2));
    fireEvent.change(screen.getByRole("textbox", { name: "搜索待处理记录" }), { target: { value: "SKU-12" } });
    await waitFor(() => expect(screen.getAllByRole("button", { name: "指定超收" })).toHaveLength(1));
    expect(screen.queryByRole("button", { name: /按调整重算/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("checkbox").at(-1)!);
    expect(screen.getByRole("button", { name: "线下处理" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "转交货批次" })).toBeEnabled();
  });

  it("指定超收保存后保持抽屉锁定，整链完成自动刷新分配并提示差值", async () => {
    const record = createDetailExceptions()[3];
    state.exceptions = [record];
    const computed = deferred<Response>();
    const exported = deferred<Response>();
    let allocationReads = 0;
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/jobs/88")) return computed.promise;
        if (url.endsWith("/api/jobs/89")) return exported.promise;
        if (url.includes("/inbound-allocation")) {
          allocationReads += 1;
          return jsonResponse({
            batch_id: 7,
            supplier_code: "GYS-023",
            batch_updated_at: state.batch.updated_at,
            allowance_limit: record.manual_quantity,
            remaining_quantity: allocationReads === 1 ? record.manual_quantity : 5,
            items: [
              {
                id: "1",
                inbound_no: "WV-1",
                po_code: "PO-1",
                current_quantity: allocationReads === 1 ? 10 : 20,
                extra_quantity: 0
              }
            ]
          });
        }
        if (url.endsWith("/adjustments")) {
          state.batch.status = "queued";
          state.batch.jobs = { compute: fixtureJob({ status: "queued" }) };
          return jsonResponse(state.batch);
        }
        return originalFetch(input, init);
      })
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "指定超收" }));
    const drawer = within(await screen.findByRole("dialog"));
    expect(drawer.getByText("处理依据 · " + record.sku)).toBeVisible();
    fireEvent.change(await drawer.findByRole("spinbutton", { name: "追加超收 PO-1 WV-1" }), { target: { value: "2" } });
    fireEvent.click(drawer.getByRole("button", { name: "保存并重算" }));
    expect(await drawer.findByText("正在重算整批，完成后自动刷新")).toBeVisible();
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(drawer.getByRole("spinbutton", { name: "追加超收 PO-1 WV-1" })).toBeDisabled();
    expect(drawer.getByRole("textbox", { name: "原因" })).toBeDisabled();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/adjustments"))).toHaveLength(1);
    state.batch = {
      ...state.batch,
      status: "succeeded",
      jobs: {
        compute: fixtureJob({ status: "succeeded", finished_at: "2026-11-05T00:00:10Z" }),
        export: fixtureJob({ id: 89, kind: "export", status: "queued" })
      }
    };
    await act(async () => {
      computed.resolve(jsonResponse(state.batch.jobs.compute));
    });
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("/api/jobs/89"))).toBe(true)
    );
    expect(drawer.getByRole("spinbutton", { name: "追加超收 PO-1 WV-1" })).toBeDisabled();
    expect(allocationReads).toBe(1);
    state.batch.download_ready = true;
    state.batch.updated_at = "2026-11-05T00:00:20Z";
    state.batch.jobs.export = fixtureJob({
      id: 89,
      kind: "export",
      status: "succeeded",
      finished_at: state.batch.updated_at
    });
    state.exceptions = [];
    await act(async () => {
      exported.resolve(jsonResponse(state.batch.jobs.export));
    });
    expect(await drawer.findByText("本次分配 +10，待处理剩余 5")).toBeVisible();
    expect(drawer.getByRole("spinbutton", { name: "追加超收 PO-1 WV-1" })).toBeEnabled();
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(allocationReads).toBe(2);
  });

  it.each([true, false])("准确展示API锁定和手动来源：%s", async (apiSource) => {
    if (!apiSource) {
      delete state.batch.version_ids.self_operated_inbound;
      delete state.batch.versions.self_operated_inbound;
    }
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "来源文件 2" }));
    const materials = within(screen.getByRole("tabpanel", { name: "来源文件 2" }));
    expect(materials.getByRole("columnheader", { name: "本次申请" })).toBeInTheDocument();
    expect(materials.getByRole("columnheader", { name: "可入库" })).toBeInTheDocument();
    expect(
      await screen.findByText(new RegExp(`待入库数据：.*（${apiSource ? "API 锁定" : "手动上传"}）`))
    ).toBeInTheDocument();
    if (apiSource) {
      fireEvent.click(screen.getByRole("tab", { name: "锁定资料" }));
      expect(screen.getByText("待入库 API 数据")).toBeInTheDocument();
    }
  });

  it("缺少待入库数据时保留上传能力并禁止预检", async () => {
    state.batch.status = "draft";
    state.batch.inbound_file = { uploaded: false, original_name: "" };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "当前批次任务" }));
    expect(task.getByRole("status")).toHaveTextContent("待入库数据尚未就绪");
    expect(task.getByRole("button", { name: /预检/ })).toBeDisabled();
    expect(task.getByRole("button", { name: /上传自营仓入库单/ })).toBeEnabled();
  });

  it("草稿只调用预检，由后端接续计算，不显示独立预检或开始审校", async () => {
    state.batch.status = "draft";
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/preflight")) return jsonResponse(state.batch);
        return originalFetch(input, init);
      })
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "当前批次任务" }));
    const button = task.getByRole("button", { name: "预检并计算" });
    expect(task.queryByRole("button", { name: /^预检$/ })).not.toBeInTheDocument();
    expect(task.queryByRole("button", { name: "开始审校" })).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(await screen.findByText("已提交预检，通过后自动计算")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toEqual([
      ["/api/batches/7/preflight", expect.objectContaining({ method: "POST" })]
    ]);
  });

  it("失败时保留重新计算，低频取数入口放在更多菜单", async () => {
    state.batch.status = "failed";
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "当前批次任务" }));
    expect(task.getByRole("button", { name: /重新计算/ })).toBeEnabled();
    expect(task.queryByRole("button", { name: /预检/ })).not.toBeInTheDocument();
    expect(task.queryByRole("button", { name: "重新取数" })).not.toBeInTheDocument();
    fireEvent.click(task.getByRole("button", { name: /更多/ }));
    expect(await screen.findByRole("menuitem", { name: "重新取数" })).toBeInTheDocument();
  });

  it.each([true, false])("区分有效零值与缺失汇总：%s", async (hasSummary) => {
    state.batch.summary = hasSummary
      ? { delivery_total: 0, import_total: 0, manual_total: 0, conserved: true }
      : undefined;
    state.batch.receipt = hasSummary
      ? { cumulative_total: 0, history_total: 0, requested_total: 0, issue_count: 0 }
      : undefined;
    state.exceptions = [];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const task = within(await screen.findByRole("region", { name: "当前批次任务" }));
    const summary = task.getByLabelText("入库数量摘要");
    expect(summary).toHaveTextContent(hasSummary ? "可入库 0" : "可入库 —");
    expect(summary).toHaveTextContent(hasSummary ? "待处理 0" : "待处理 —");
  });
});
