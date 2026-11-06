import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BatchSummary from "./BatchSummary";
import { createDetailBatch } from "./detailFixtures";

describe("BatchSummary", () => {
  it.each(["delivery", "self_operated_inbound"] as const)("%s 共用双环和真实批次数字", (workflow) => {
    const batch = { ...createDetailBatch(), workflow, receipt: { requested_total: 14304 } };
    batch.summary = { delivery_total: 14304, import_total: 6254, manual_total: 8050, conserved: true };
    const { container } = render(<BatchSummary batch={batch} reviewStats={{ resolvedCount: 6, totalCount: 18 }} />);
    const lines = container.querySelectorAll(".quantity-summary-line");
    expect(lines[0]).toHaveTextContent(`6,254 / 14,304 ${workflow === "delivery" ? "可导入" : "可入库"}`);
    expect(lines[1]).toHaveTextContent(`6 / 18 条 ${workflow === "delivery" ? "已审校" : "已处理"}`);
    expect(screen.getByText("待处理 8,050 件")).toBeVisible();
    expect(screen.getByRole("img")).toHaveAccessibleName(/占比 43.7%.*占比 33.3%/);
    expect(container.querySelectorAll("circle")).toHaveLength(4);
  });

  it("数量只依赖 batch.summary，不从来源文件推导", () => {
    const batch = createDetailBatch();
    batch.summary = { delivery_total: 50, import_total: 35, manual_total: 15, conserved: true };
    render(<BatchSummary batch={batch} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/交货 50 = 可导入 35 \+ 待处理 15/);
    expect(screen.getByText("待处理 15 件")).toBeInTheDocument();
  });

  it("守恒失败仍显示原始业务数量和错误", () => {
    const batch = createDetailBatch();
    batch.summary = { delivery_total: 161, import_total: 100, manual_total: 60, conserved: false };
    render(<BatchSummary batch={batch} />);
    expect(screen.getByText("数量不守恒：交货 161 ≠ 可导入 100 + 待处理 60")).toHaveClass("conservation-bad");
  });

  it.each(["draft", "missing"])("%s 无计算结果时显示未知值和轨道", (state) => {
    const batch = createDetailBatch();
    if (state === "draft") batch.status = "draft";
    else delete batch.summary;
    const { container } = render(<BatchSummary batch={batch} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/可导入 — \/ — 件，占比 —.*尚未计算/);
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    expect(container.querySelector("circle[stroke-dasharray]")).not.toBeInTheDocument();
  });

  it("统计未读取时保持内环未知，不虚构零条已审校", () => {
    render(<BatchSummary batch={createDetailBatch()} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/待处理已审校 — \/ — 条，占比 —/);
  });

  it("历史仅汇总已确认部分，点击小字查看累计实收、历史与未确认行数", async () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      status: "preflight_ready",
      summary: undefined,
      receipt: { cumulative_total: 23, history_total: 3, requested_total: 20, issue_count: 0, unconfirmed_count: 1 }
    };
    render(<BatchSummary batch={batch} />);
    expect(screen.queryByText("历史已入库", { exact: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "累计实收 − 历史已入库" }));
    expect((await screen.findByText("历史已入库", { exact: true })).parentElement).toHaveTextContent("历史已入库 3");
    expect(screen.getByText("累计实收", { exact: true }).parentElement).toHaveTextContent("累计实收 23");
    expect(screen.getByText("未确认行数", { exact: true }).parentElement).toHaveTextContent("未确认行数 1");
    expect(screen.getByRole("img")).toHaveAccessibleName(/可入库 — \/ 20 件，占比 —.*尚未计算/);
    expect(screen.queryByText(/处待核对/)).not.toBeInTheDocument();
  });

  it("自营仓待核对保留真实问题数量，不伪造可入库", () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      receipt: { cumulative_total: 100, history_total: null, requested_total: null, issue_count: 1 }
    };
    const { container } = render(<BatchSummary batch={batch} />);
    expect(screen.getByText("尚未计算，1 处待核对")).toBeVisible();
    expect(container.querySelectorAll("circle")).toHaveLength(2);
  });
});
