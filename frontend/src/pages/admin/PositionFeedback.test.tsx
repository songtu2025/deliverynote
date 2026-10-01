import { render, screen } from "@testing-library/react";
import { ConfigProvider } from "antd";
import { describe, expect, it } from "vitest";

import { IssueList } from "./PositionFeedback";

describe("PositionFeedback IssueList", () => {
  it("keeps the default empty-state message", () => {
    render(<IssueList issues={[]} />);
    expect(screen.getByText("没有发现问题")).toBeInTheDocument();
  });

  it("keeps row and whole-sheet descriptions for existing dialog callers", () => {
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <IssueList
          issues={[
            { severity: "error", code: "synthetic", message: "合成行错误", row_numbers: [4, 2] },
            { severity: "warning", code: "synthetic", message: "合成全表警告", row_numbers: [] }
          ]}
        />
      </ConfigProvider>
    );
    expect(screen.getByText("第 4、2 行")).toBeInTheDocument();
    expect(screen.getByText("全表")).toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(2);
  });

  it("supports quality context without adding a second list or wrapper", () => {
    const { container } = render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <IssueList
          issues={[{ severity: "warning", code: "synthetic", message: "合成问题", row_numbers: [2] }]}
          className="input-data-quality-list"
          describeRows={(issue) => `涉及 Excel 行：${issue.row_numbers.join("、")}`}
        >
          <span>合成统计</span>
        </IssueList>
      </ConfigProvider>
    );
    expect(screen.getByText("合成统计")).toBeInTheDocument();
    expect(screen.getByText("涉及 Excel 行：2")).toBeInTheDocument();
    const list = container.querySelector(".input-data-quality-list");
    expect(list).toHaveStyle({ width: "100%" });
    expect(list?.children).toHaveLength(2);
  });
});
