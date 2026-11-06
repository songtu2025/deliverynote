import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import QuantityRings from "./QuantityRings";

const outer = { label: "可导入", value: 6254, total: 14304 };
const inner = { label: "待处理已审校", value: 6, total: 18 };

describe("QuantityRings", () => {
  it("两环按真实比例扣除圆头长度，不让圆头虚增占比", () => {
    const { container } = render(<QuantityRings outer={outer} inner={inner} />);
    const arcs = container.querySelectorAll("circle[stroke-dasharray]");
    expect(arcs).toHaveLength(2);
    [outer, inner].forEach((metric, index) => {
      const radius = index === 0 ? 54 : 37;
      const circumference = 2 * Math.PI * radius;
      const [length, gap] = arcs[index].getAttribute("stroke-dasharray")!.split(" ").map(Number);
      expect(length + Number(arcs[index].getAttribute("stroke-width"))).toBeCloseTo(
        (circumference * metric.value) / metric.total
      );
      expect(gap).toBeCloseTo(circumference);
      expect(arcs[index]).toHaveAttribute("stroke-linecap", "round");
    });
    expect(screen.getByRole("img")).toHaveAttribute("width", "112");
  });

  it("小于圆头宽度的非零占比不画虚假的最小弧长", () => {
    const { container } = render(<QuantityRings outer={{ ...outer, value: 1, total: 10000 }} />);
    const arc = container.querySelector("circle[stroke-dasharray]")!;
    const length = Number(arc.getAttribute("stroke-dasharray")!.split(" ")[0]);
    expect(length).toBeGreaterThan(0);
    expect(length + Number(arc.getAttribute("stroke-width"))).toBeCloseTo((2 * Math.PI * 54) / 10000);
  });

  it.each([0, 100])("%s%% 时只显示轨道或完整闭环", (value) => {
    const metric = { ...outer, value, total: 100 };
    const { container } = render(<QuantityRings outer={metric} inner={metric} />);
    expect(container.querySelectorAll("circle")).toHaveLength(value === 0 ? 2 : 4);
    expect(container.querySelector("circle[stroke-dasharray]")).not.toBeInTheDocument();
  });

  it("空分母不显示完成状态，未知值保持未知", () => {
    const { container } = render(<QuantityRings small outer={{ label: "可导入", value: 0, total: 0 }} />);
    expect(container.querySelectorAll("circle")).toHaveLength(1);
    expect(container.querySelector("path")).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName("可导入 0 / 0 件，占比 0.0%");
  });

  it("多实例渐变 id 全局唯一且每个填充引用自身渐变", () => {
    const { container } = render(
      <>
        <QuantityRings outer={outer} inner={inner} />
        <QuantityRings outer={outer} inner={inner} />
      </>
    );
    const ids = Array.from(container.querySelectorAll("linearGradient"), (gradient) => gradient.id);
    expect(new Set(ids).size).toBe(4);
    container.querySelectorAll("svg").forEach((svg) => {
      const gradients = Array.from(svg.querySelectorAll("linearGradient"), (gradient) => gradient.id);
      const references = Array.from(svg.querySelectorAll("circle[stroke-dasharray]"), (arc) =>
        arc.getAttribute("stroke")
      );
      expect(references).toEqual(gradients.map((id) => `url(#${id})`));
    });
  });

  it("中文 aria 包含数量、占比与守恒，键盘聚焦显示 Tooltip", async () => {
    render(<QuantityRings outer={outer} inner={inner} description="交货 14,304 = 可导入 6,254 + 待处理 8,050" />);
    const svg = screen.getByRole("img", { name: /可导入 6,254 \/ 14,304 件，占比 43.7%/ });
    expect(svg).toHaveAccessibleName(/待处理已审校 6 \/ 18 条，占比 33.3%/);
    expect(svg).toHaveAttribute("tabindex", "0");
    fireEvent.focus(svg);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("交货 14,304 = 可导入 6,254 + 待处理 8,050");
    fireEvent.blur(svg);
  });

  it("28px 小环只有外环，全量可导入时打勾", () => {
    const { container, rerender } = render(<QuantityRings small outer={outer} inner={inner} />);
    expect(screen.getByRole("img")).toHaveAttribute("width", "28");
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    expect(container.querySelector("path")).not.toBeInTheDocument();
    rerender(<QuantityRings small outer={{ ...outer, value: outer.total }} />);
    expect(container.querySelector("path")).toHaveAttribute("aria-label", "全部可导入");
    expect(container.querySelector("circle[stroke-dasharray]")).not.toBeInTheDocument();
  });
});
