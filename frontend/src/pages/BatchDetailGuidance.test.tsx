import { fireEvent, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";

describe("BatchDetailGuidance", () => {
  const { state } = setupBatchDetailTest();

  it.each(["delivery", "self_operated_inbound"] as const)("%s 列表展示商品与入库单依据", async (workflow) => {
    state.batch.workflow = workflow;
    if (workflow === "self_operated_inbound") {
      state.batch.inbound_file = { uploaded: true, original_name: "合成待入库.xlsx" };
      state.batch.receipt = { cumulative_total: 160, history_total: 0, requested_total: 160, issue_count: 0 };
    }
    state.batch.files[1].document_note = "LN-1、LN-2";
    state.exceptions = [
      { ...state.exceptions[0], reason_code: "product_not_found", reason: "产品信息未匹配" },
      { ...state.exceptions[1], reason_code: "inbound_order_not_found", reason: "未找到自营仓入库单" }
    ];
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const productRow = (await screen.findByText("SKU-A")).closest("tr")!;
    const inboundRow = screen.getByText("SKU-B").closest("tr")!;
    expect(productRow).toHaveTextContent("原始站点 US：锁定商品资料无此 SKU 的该站点记录");
    expect(inboundRow).toHaveTextContent("交货单号 LN-1、LN-2 下无此 SKU、站点的入库单");
    expect(screen.queryByText("查看异常原因后处理")).not.toBeInTheDocument();
    if (workflow === "self_operated_inbound") {
      fireEvent.click(within(inboundRow).getByRole("button", { name: "SKU-B" }));
      const drawer = within(await screen.findByRole("dialog"));
      expect(drawer.getByText("处理建议")).toBeVisible();
      expect(drawer.getByRole("region", { name: "原因指导" })).toHaveTextContent("请在积加核对关联交货单和商品站点");
    }
  });

  it("shows reason-specific review guidance and uses candidate sites as choices", async () => {
    state.exceptions[2].reason = "候选站点需要确认";
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    await screen.findByRole("tab", { name: /^待处理 \d/ });

    expect(await screen.findByRole("columnheader", { name: "原因与依据" })).toBeInTheDocument();

    const excessRow = (await screen.findByText("SKU-A")).closest("tr");
    expect(excessRow).not.toBeNull();
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("已分配 20");
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("超出 60");
    expect(excessRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("未命中超收规则");
    fireEvent.click(within(excessRow!).getByRole("button", { name: /^审校 SKU-/, hidden: true }));
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
    fireEvent.click(within(noPurchaseRow!).getByRole("button", { name: /^审校 SKU-/, hidden: true }));
    drawer = screen.getByRole("dialog");
    expect(within(drawer).getByText("核对锁定采购版本")).toBeInTheDocument();
    fireEvent.focus(within(drawer).getByRole("button", { name: "采购核对说明" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "锁定的采购数据里没有这个 SKU 的未交量，请核对供应商、站点和目的仓。"
    );
    fireEvent.click(within(drawer).getByRole("button", { name: "Close" }));

    const ambiguousRow = screen.getByText("SKU-C").closest("tr");
    expect(ambiguousRow).not.toBeNull();
    expect(within(ambiguousRow!).getByText("2 个候选站点")).toHaveAttribute("title", state.exceptions[2].full_site);
    expect(within(ambiguousRow!).getByText("文件 2")).toHaveAttribute("title", state.batch.files[1].original_name);
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("候选站点");
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("AMAZON:OTHER:US");
    expect(ambiguousRow!.querySelector(".exception-evidence-cell")).toHaveTextContent("AMAZON:SEEKWAY:US");
    fireEvent.click(within(ambiguousRow!).getByRole("button", { name: /^审校 SKU-/, hidden: true }));
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
    fireEvent.click(within(allowanceRow!).getByRole("button", { name: /^审校 SKU-/, hidden: true }));
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
