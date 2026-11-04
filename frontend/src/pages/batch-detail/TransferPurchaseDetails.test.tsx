import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderDetail } from "../batchDetailTestSupport";
import type { TransferOptions } from "../../exceptionTransferApi";
import TransferPurchaseDetails, { transferSiteOptions } from "./TransferPurchaseDetails";

const data: TransferOptions = {
  sites: ["AMAZON:EMPTY:DE", "AMAZON:SEEKWAY:JP", "AMAZON:OTHER:US"],
  purchases: [
    { id: "1", po_code: "PO-JP", site: "AMAZON:SEEKWAY:JP", warehouse: "本地仓", remaining_quantity: 42 },
    ...[1, 2, 3, 4].map((id) => ({
      id: String(id + 1),
      po_code: `PO-US-${id}`,
      site: "AMAZON:OTHER:US",
      warehouse: "广州仓",
      remaining_quantity: id
    }))
  ],
  purchase_error: null,
  queried_at: null
};

describe("转交采购去向", () => {
  it("只显示所选站点前两张采购，悬停 +N 显示全部，切换站点即时更新", async () => {
    const { rerender } = renderDetail(<TransferPurchaseDetails data={data} site="AMAZON:OTHER:US" />);
    expect(screen.getByText("PO-US-1")).toBeInTheDocument();
    expect(screen.getByText("PO-US-2")).toBeInTheDocument();
    expect(screen.queryByText("PO-US-3")).not.toBeInTheDocument();
    expect(screen.queryByText("PO-JP")).not.toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "+2" }));
    const all = await screen.findByRole("tooltip");
    for (const id of [1, 2, 3, 4]) expect(within(all).getByText(`PO-US-${id}`)).toBeInTheDocument();
    rerender(<TransferPurchaseDetails data={data} site="AMAZON:SEEKWAY:JP" />);
    expect(screen.getByText("PO-JP")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+2" })).not.toBeInTheDocument();
  });

  it("无采购显示简短空状态，采购错误显示原因", () => {
    const { rerender } = renderDetail(<TransferPurchaseDetails data={data} site="AMAZON:EMPTY:DE" />);
    expect(screen.getByText("无未交采购")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    rerender(<TransferPurchaseDetails data={{ ...data, purchase_error: "采购读取失败" }} site="AMAZON:OTHER:US" />);
    expect(screen.getByText("采购读取失败")).toBeInTheDocument();
    expect(screen.queryByText("PO-US-1")).not.toBeInTheDocument();
  });

  it("采购字段中的 HTML 特殊字符按文本显示", () => {
    renderDetail(
      <TransferPurchaseDetails
        data={{ ...data, purchases: [{ ...data.purchases[0], po_code: "<script>采购</script>" }] }}
        site="AMAZON:SEEKWAY:JP"
      />
    );
    expect(screen.getByText("<script>采购</script>").querySelector("script")).toBeNull();
  });

  it("站点按未交降序排列，零余额置后且使用次要色", () => {
    const options = transferSiteOptions(data);
    expect(options.map((option) => option.label)).toEqual([
      "SEEKWAY:JP · 未交 42",
      "OTHER:US · 未交 10",
      "EMPTY:DE · 未交 0"
    ]);
    expect(options[2].style).toEqual({ color: "var(--dn-muted)" });
  });
});
