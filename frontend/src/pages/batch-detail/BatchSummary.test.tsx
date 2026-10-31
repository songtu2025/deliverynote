import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BatchSummary from "./BatchSummary";
import { createDetailBatch } from "./detailFixtures";

describe("BatchSummary", () => {
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

  it("没有计算结果时不显示数量条", () => {
    const batch = createDetailBatch();
    batch.status = "draft";
    render(<BatchSummary batch={batch} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("缺少批次汇总时不显示数量条", () => {
    const batch = createDetailBatch();
    delete batch.summary;
    render(<BatchSummary batch={batch} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
