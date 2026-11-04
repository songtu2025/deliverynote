import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";
import { fixtureJob, fixtureVersion } from "./batch-detail/detailFixtures";
import { jsonResponse } from "./admin/positionDraftTestSupport";

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
    expect(page.getByText("查看并处理").closest("button")).toBeEnabled();
    expect(page.queryByText("保存并重新计算")).not.toBeInTheDocument();
  });

  it.each([
    ["compute", "queued", "计算排队中"],
    ["compute", "running", "正在计算"],
    ["export", "queued", "结果排队中"],
    ["export", "running", "正在生成结果"]
  ] as const)("恢复真实任务状态 %s/%s", async (kind, status, title) => {
    state.batch.jobs = { [kind]: fixtureJob({ kind, status }) };
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent(title);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
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

  it.each(["draft", "failed"])("%s 批次仍独立预检，不自动启动计算", async (status) => {
    state.batch.status = status;
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
    const button = task.getByRole("button", { name: /预检/ });
    expect(button).toHaveTextContent(/^预检$/);
    expect(task.queryByRole("button", { name: /预检并计算/ })).not.toBeInTheDocument();
    expect(task.queryByRole("button", { name: /重新计算/ }) !== null).toBe(status === "failed");
    expect(task.getByRole("status")).toHaveTextContent(
      status === "draft" ? "2 份质检交货单已上传，确认顺序后预检" : "计算失败"
    );
    fireEvent.click(button);
    expect(await screen.findByText("已提交后台预检，正在获取历史并核对累计实收")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toEqual([
      ["/api/batches/7/preflight", expect.objectContaining({ method: "POST" })]
    ]);
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
