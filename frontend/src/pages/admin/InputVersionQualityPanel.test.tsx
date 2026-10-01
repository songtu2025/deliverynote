import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InputVersionQualityPanel } from "./InputVersionQualityPanel";

type QualityProps = ComponentProps<typeof InputVersionQualityPanel>;

function qualityProps(): QualityProps {
  return {
    kind: "position",
    hasActiveVersion: true,
    summary: { kind: "position", row_count: 2, columns: [], metrics: {}, issues: [] },
    errors: 0,
    warnings: 0
  };
}

function qualityView(props: QualityProps) {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <InputVersionQualityPanel {...props} />
    </ConfigProvider>
  );
}

describe("InputVersionQualityPanel", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("distinguishes no active version from waiting for inspection", () => {
    const props = qualityProps();
    props.hasActiveVersion = false;
    props.summary = null;
    const view = render(qualityView(props));
    expect(screen.getByText("启用资料后显示检查结果。")).toBeInTheDocument();
    view.rerender(qualityView({ ...props, hasActiveVersion: true }));
    expect(screen.getByText("等待检查结果。")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["product", "template", "inbound_template"] as const)("does not claim content quality for %s", (kind) => {
    const props = qualityProps();
    props.kind = kind;
    render(qualityView(props));
    expect(screen.getByText("文件结构已通过校验，当前未执行内容质量诊断")).toBeInTheDocument();
    expect(screen.queryByText("未发现资料质量问题")).not.toBeInTheDocument();
  });

  it.each(["supplier", "position"] as const)("shows the no-issues result for %s", (kind) => {
    render(qualityView({ ...qualityProps(), kind }));
    expect(screen.getByText("未发现资料质量问题")).toBeInTheDocument();
  });

  it.each(["error", "warning"] as const)("preserves %s severity and server row order", (severity) => {
    const props = qualityProps();
    props.summary!.issues = [{ severity, code: "synthetic", message: "合成问题", row_numbers: [9, 2] }];
    props.errors = severity === "error" ? 2 : 0;
    props.warnings = severity === "warning" ? 2 : 0;
    render(qualityView(props));
    expect(screen.getByText(`${props.errors} 个错误`)).toBeInTheDocument();
    expect(screen.getByText(`${props.warnings} 个警告`)).toBeInTheDocument();
    expect(screen.getByText("涉及 Excel 行：9、2")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: severity === "error" ? "close-circle" : "exclamation-circle" })
    ).toBeInTheDocument();
  });

  it("uses parent totals and preserves mixed issues without mutating inspection", () => {
    const props = qualityProps();
    props.summary!.issues = [
      { severity: "error", code: "synthetic", message: "合成错误", row_numbers: [2, 3] },
      { severity: "warning", code: "synthetic", message: "合成警告", row_numbers: [] }
    ];
    props.errors = 2;
    props.warnings = 1;
    const original = structuredClone(props.summary);
    render(qualityView(props));
    expect(screen.getAllByRole("alert").map((alert) => alert.textContent)).toEqual([
      "合成错误涉及 Excel 行：2、3",
      "合成警告"
    ]);
    expect(screen.getByText("2 个错误")).toBeInTheDocument();
    expect(screen.getByText("1 个警告")).toBeInTheDocument();
    expect(screen.queryByText("全表")).not.toBeInTheDocument();
    expect(props.summary).toEqual(original);
  });

  it("replaces old issues and counts when the parent supplies another kind", () => {
    const props = qualityProps();
    props.summary!.issues = [{ severity: "error", code: "synthetic", message: "合成旧问题", row_numbers: [2] }];
    props.errors = 1;
    const view = render(qualityView(props));
    expect(screen.getByText("合成旧问题")).toBeInTheDocument();
    view.rerender(qualityView({ ...qualityProps(), kind: "supplier" }));
    expect(screen.getByText("未发现资料质量问题")).toBeInTheDocument();
    expect(screen.queryByText("合成旧问题")).not.toBeInTheDocument();
    expect(screen.queryByText("1 个错误")).not.toBeInTheDocument();
  });

  it("renders HTML and long messages as text", () => {
    const props = qualityProps();
    const message = '<img src=x onerror="window.__uiInjected=true">' + "合成长文本".repeat(80);
    props.summary!.issues = [{ severity: "warning", code: "synthetic", message, row_numbers: [2] }];
    props.warnings = 1;
    const { container } = render(qualityView(props));
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
