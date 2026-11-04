import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BatchSummary from "./BatchSummary";
import { createDetailBatch } from "./detailFixtures";

describe("BatchSummary", () => {
  it("历史仅汇总已确认部分，并标注未确认行但不计入待核对", () => {
    render(
      <BatchSummary
        batch={{
          ...createDetailBatch(),
          status: "preflight_ready",
          workflow: "self_operated_inbound",
          summary: undefined,
          receipt: { cumulative_total: 23, history_total: 3, requested_total: 20, issue_count: 0, unconfirmed_count: 1 }
        }}
      />
    );
    expect(screen.getByText("历史已入库").parentElement).toHaveTextContent("历史已入库 3 · 1 行未确认");
    expect(screen.getByRole("img", { name: "尚未计算" })).toBeInTheDocument();
  });
  it("始终按批次汇总显示可导入和待处理两段及图例", () => {
    const { container } = render(<BatchSummary batch={createDetailBatch()} />);
    const bar = screen.getByRole("img", { name: "可导入 100，待处理 60" });
    expect(bar.children).toHaveLength(2);
    expect(bar.children[0]).toHaveStyle({ flexGrow: "100" });
    expect(bar.children[1]).toHaveStyle({ flexGrow: "60" });
    expect(bar.children[1]).toHaveClass("quantity-pending");
    const legend = container.querySelector(".batch-quantity-legend") as HTMLElement;
    expect(legend.children).toHaveLength(2);
    expect(within(legend).getByText("可导入")).toHaveTextContent("可导入 100");
    expect(within(legend).getByText("待处理")).toHaveTextContent("待处理 60");
    expect(screen.getByText("交货 160 = 可导入 100 + 待处理 60")).toHaveClass("conservation-ok");
  });

  it("数量只依赖 batch.summary，不从文件数量推导", () => {
    const batch = createDetailBatch();
    batch.summary = { delivery_total: 50, import_total: 35, manual_total: 15, conserved: true };
    render(<BatchSummary batch={batch} />);
    const bar = screen.getByRole("img", { name: "可导入 35，待处理 15" });
    expect(bar.children).toHaveLength(2);
    expect(bar.children[0]).toHaveStyle({ flexGrow: "35" });
    expect(bar.children[1]).toHaveStyle({ flexGrow: "15" });
    expect(screen.queryByText("保留待处理")).not.toBeInTheDocument();
    expect(screen.queryByText("待审校")).not.toBeInTheDocument();
  });

  it("守恒失败时保留错误提示和原始业务数量", () => {
    const batch = createDetailBatch();
    batch.summary = { delivery_total: 161, import_total: 100, manual_total: 60, conserved: false };
    render(<BatchSummary batch={batch} />);
    expect(screen.getByText("数量不守恒：交货 161 ≠ 可导入 100 + 待处理 60")).toHaveClass("conservation-bad");
  });

  it("没有计算结果时保留卡片与未知值，不用警告色", () => {
    const batch = createDetailBatch();
    batch.status = "draft";
    render(<BatchSummary batch={batch} />);
    expect(screen.getByRole("img", { name: "尚未计算" })).toHaveClass("quantity-uncomputed");
    expect(screen.getAllByText("—")).toHaveLength(5);
    expect(document.querySelectorAll(".quantity-unknown")).toHaveLength(3);
    expect(document.querySelector(".metric-pending")).not.toBeInTheDocument();
  });

  it("缺少批次汇总时不显示数量条", () => {
    const batch = createDetailBatch();
    delete batch.summary;
    render(<BatchSummary batch={batch} />);
    expect(screen.getByRole("img", { name: "尚未计算" })).toHaveClass("quantity-uncomputed");
  });

  it("自营仓未知值为灰色横线，待核对只标记珊瑚段", () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      status: "draft",
      receipt: { cumulative_total: 100, history_total: null, requested_total: null, issue_count: 1 }
    };
    const { container } = render(<BatchSummary batch={batch} />);
    expect(container.querySelectorAll(".quantity-unknown")).toHaveLength(4);
    expect(screen.queryByText("计算后生成")).not.toBeInTheDocument();
    expect(screen.queryByText("待核对", { selector: ".batch-quantity-metric strong" })).not.toBeInTheDocument();
    const bar = screen.getByRole("img", { name: "1 处待核对，其余未计算" });
    expect(bar.children).toHaveLength(1);
    expect(bar.firstElementChild).toHaveClass("quantity-pending");
    expect(container.querySelector(".quantity-import")).not.toBeInTheDocument();
  });

  it("零数量不画虚假的最小色段，自营仓使用真实汇总比例", () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      receipt: { requested_total: 160 }
    };
    batch.summary = { delivery_total: 160, import_total: 160, manual_total: 0, conserved: true };
    render(<BatchSummary batch={batch} />);
    const bar = screen.getByRole("img", { name: "可入库 160，待处理 0" });
    expect(bar.children).toHaveLength(1);
    expect(bar.firstElementChild).toHaveStyle({ flexGrow: "160" });
  });
});
