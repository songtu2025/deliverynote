import { fireEvent, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";

describe("BatchDetailGuidance", () => {
  const { state } = setupBatchDetailTest();

  it("shows reason-specific review guidance and uses candidate sites as choices", async () => {
    state.exceptions[2].reason = "候选站点需要确认";
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByRole("columnheader", { name: "审校依据" })).toBeInTheDocument();

    const excessRow = (await screen.findByText("SKU-A")).closest("tr");
    expect(excessRow).not.toBeNull();
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("已分配 20");
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("超出 60");
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("未命中超收规则");
    fireEvent.click(within(excessRow!).getByRole("button", { name: "查看并处理" }));
    let drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("采购量与超出量")).toBeInTheDocument();
    expect(within(drawer).getByText("已分配量")).toBeInTheDocument();
    expect(within(drawer).getByText("超出量")).toBeInTheDocument();
    expect(within(drawer).getByText("未命中本批次超收规则")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const noPurchaseRow = screen.getByText("SKU-B").closest("tr");
    expect(noPurchaseRow).not.toBeNull();
    expect(noPurchaseRow!.querySelector(".exception-evidence-cell")).toHaveTextContent(
      "需核对 供应商、SKU、站点、目的仓"
    );
    fireEvent.click(within(noPurchaseRow!).getByRole("button", { name: "查看并处理" }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("核对锁定采购版本")).toBeInTheDocument();
    expect(within(drawer).getByText(/供应商、SKU、站点和目的仓/)).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const ambiguousRow = screen.getByText("SKU-C").closest("tr");
    expect(ambiguousRow).not.toBeNull();
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("候选站点");
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("AMAZON:OTHER:US");
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("AMAZON:SEEKWAY:US");
    fireEvent.click(within(ambiguousRow!).getByRole("button", { name: "查看并处理" }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("选择候选站点")).toBeInTheDocument();
    const siteChoice = within(drawer).getByRole("radio", { name: "AMAZON:SEEKWAY:US" });
    fireEvent.click(siteChoice);
    expect(siteChoice).toBeChecked();
    expect(within(drawer).queryByRole("textbox", { name: "完整站点" })).not.toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const allowanceRow = screen.getByText("SKU-D").closest("tr");
    expect(allowanceRow).not.toBeNull();
    expect(allowanceRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("正常采购 20");
    expect(allowanceRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("使用超收 50");
    expect(allowanceRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("剩余 0");
    fireEvent.click(within(allowanceRow!).getByRole("button", { name: "查看并处理" }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("超收额度使用情况")).toBeInTheDocument();
    expect(within(drawer).getByText("正常采购分配")).toBeInTheDocument();
    expect(within(drawer).getByText("本条使用超收额度")).toBeInTheDocument();
    expect(within(drawer).getByText("剩余额度")).toBeInTheDocument();
    const guidance = within(drawer).getByRole("region", { name: "原因指导" });
    expect(within(guidance).getByText("20")).toBeInTheDocument();
    expect(within(guidance).getByText("50")).toBeInTheDocument();
    expect(within(guidance).getByText("0")).toBeInTheDocument();
  }, 30_000);
});
