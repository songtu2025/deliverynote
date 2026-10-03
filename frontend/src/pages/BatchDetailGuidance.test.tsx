import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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

  it("recomputes a self-operated batch after selecting an ambiguous site", async () => {
    state.batch = {
      ...state.batch,
      workflow: "self_operated_inbound",
      name: "2026-08-21 自营仓入库批次",
      self_operated_overreceipt_rule: {
        id: 10,
        name: "自营仓超收 5 件",
        allowance: 5,
        active: false,
        created_by: 1,
        created_at: "2026-08-21T08:00:00"
      },
      inbound_file: {
        original_name: "自营仓收货入库单.xlsx",
        uploaded: true
      },
      file_count: 1,
      files: [state.batch.files[0]],
      summary: {
        delivery_total: 27,
        import_total: 0,
        manual_total: 27,
        conserved: true
      }
    };
    state.exceptions = [state.exceptions[2], state.exceptions[3]];
    state.exceptions[0].allowed_actions = ["resolve_site"];
    state.exceptions[1].allowed_actions = [];

    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByText("自营仓入库单：自营仓收货入库单.xlsx")).toBeInTheDocument();
    expect(screen.getByText("每个供应商 + SKU + 站点共享 +5")).toBeInTheDocument();
    const ambiguousRow = screen.getByText("SKU-C").closest("tr");
    const overreceiptRow = screen.getByText("SKU-D").closest("tr");
    expect(ambiguousRow).not.toBeNull();
    expect(overreceiptRow).not.toBeNull();
    expect(within(overreceiptRow!).getByText("待处理")).toBeInTheDocument();
    expect(within(overreceiptRow!).queryByText("保留待处理")).not.toBeInTheDocument();
    fireEvent.click(within(ambiguousRow!).getByRole("button", { name: "查看并处理" }));

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).queryByRole("spinbutton", { name: "数量" })).not.toBeInTheDocument();
    const save = within(drawer).getByRole("button", { name: "保存并重新计算" });
    expect(save).toBeDisabled();
    fireEvent.click(within(drawer).getByRole("radio", { name: "AMAZON:SEEKWAY:US" }));
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/exceptions/32/self-operated-site",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ full_site: "AMAZON:SEEKWAY:US" })
        })
      );
    });
  }, 30_000);
});
