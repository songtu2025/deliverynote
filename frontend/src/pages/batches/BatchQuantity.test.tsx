import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BatchQuantity from "./BatchQuantity";
import { createDetailBatch } from "../batch-detail/detailFixtures";

describe("BatchQuantity", () => {
  it.each(["delivery", "self_operated_inbound"] as const)("%s 列表显示小环、批次汇总和待处理数量", (workflow) => {
    const batch = { ...createDetailBatch(), workflow, receipt: { requested_total: 14304 } };
    batch.summary = { delivery_total: 14304, import_total: 6254, manual_total: 8050, conserved: true };
    render(<BatchQuantity batch={batch} />);
    expect(screen.getByText("6,254").parentElement).toHaveTextContent("6,254 / 14,304");
    expect(screen.getByText("待处理 8,050")).toHaveClass("batch-list-quantity-pending");
    expect(screen.getByRole("img")).toHaveAccessibleName(
      new RegExp(`${workflow === "delivery" ? "可导入" : "可入库"} 6,254 / 14,304 件，占比 43.7%`)
    );
    expect(screen.getByRole("img")).toHaveAttribute("width", "28");
  });

  it.each(["delivery", "self_operated_inbound"] as const)("%s 全量可导入时满环打勾，不显示零待处理", (workflow) => {
    const batch = { ...createDetailBatch(), workflow, receipt: { requested_total: 160 } };
    batch.summary = { delivery_total: 160, import_total: 160, manual_total: 0, conserved: true };
    const { container } = render(<BatchQuantity batch={batch} />);
    expect(container.querySelector("path")).toBeInTheDocument();
    expect(screen.queryByText("待处理 0")).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName(/占比 100.0%/);
  });

  it("累计实收未就绪时不展示旧计算结果", () => {
    const batch = {
      ...createDetailBatch(),
      workflow: "self_operated_inbound" as const,
      receipt: { requested_total: null, issue_count: 1 }
    };
    render(<BatchQuantity batch={batch} />);
    expect(screen.getByText("尚未计算")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
