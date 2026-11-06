import { fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { getReasonDefinition, reasonCatalog } from "./reasonCatalog";
import { createDetailExceptions } from "./detailFixtures";
import { ExceptionEvidence } from "./ExceptionEvidence";
import ReasonGuidance from "./ReasonGuidance";

// 与后端 ExceptionReason 枚举逐项对应，新增原因时必须补齐说明。
const reasons = {
  product_not_found: "产品信息未匹配",
  ambiguous_product_site: "产品信息站点不唯一",
  purchase_balance_exceeded: "超出采购未交量",
  purchase_not_found: "未找到可交货采购需求",
  overreceipt_limit_exceeded: "超出允许超收量",
  inbound_order_not_found: "未找到自营仓入库单",
  supplier_mismatch: "供应商不一致",
  po_name_missing: "PO名称为空",
  receivable_invalid: "应收货无效",
  receivable_exceeded: "超出应收货"
} as const;
const record = createDetailExceptions()[0];
const context = { hasOverreceiptRule: true, documentNote: "LN-1、LN-2" };

describe("待处理原因说明表", () => {
  it("覆盖全部原因，依据、建议非空且不使用空泛兜底", () => {
    expect(Object.keys(reasonCatalog).sort()).toEqual(Object.keys(reasons).sort());
    for (const [reason_code, reason] of Object.entries(reasons)) {
      const exception = { ...record, reason_code: reason_code as keyof typeof reasons, reason };
      const definition = getReasonDefinition(reason_code);
      expect(definition.reason).toBe(reason);
      expect(getReasonDefinition(reason)).toBe(definition);
      expect(renderToStaticMarkup(<>{definition.evidence(exception, context)}</>)).not.toBe("");
      const guidance = definition.guidance(exception, context);
      expect(guidance.message.trim()).not.toBe("");
      const markup = renderToStaticMarkup(<ExceptionEvidence exception={exception} {...context} />);
      expect(markup).not.toContain("查看异常原因后处理");
      expect(markup).not.toContain("未登记的原因");
    }
  });

  it.each([
    ["product_not_found", "原始站点 US：锁定商品资料无此 SKU 的该站点记录"],
    ["inbound_order_not_found", "交货单号 LN-1、LN-2 下无此 SKU、站点的入库单"],
    ["supplier_mismatch", "入库单供应商与来源文件供应商不一致，请核对供应商名称"],
    ["po_name_missing", "入库单 PO 名称为空，请核对关联采购单"],
    ["receivable_invalid", "入库单应收货数量无效，请核对应收货字段是否为非负整数"],
    ["receivable_exceeded", "已分配 20超出 60"]
  ] as const)("%s 展示具体依据", (reason_code, text) => {
    render(<ExceptionEvidence exception={{ ...record, reason_code }} {...context} />);
    expect(document.body).toHaveTextContent(text);
  });

  it("原始站点为空时明确说明", () => {
    render(
      <ExceptionEvidence exception={{ ...record, reason_code: "product_not_found", original_site: " " }} {...context} />
    );
    expect(screen.getByText("无原始站点：锁定商品资料无此 SKU 的该站点记录")).toBeInTheDocument();
  });

  it("长交货单号截断并支持键盘聚焦查看全部，特殊字符仅作为文字", async () => {
    const documentNote = ["LN-1", "LN-2", "<img src=x onerror=alert(1)>", "LN-" + "3".repeat(40)].join("、");
    const { container } = render(
      <ExceptionEvidence
        exception={{ ...record, reason_code: "inbound_order_not_found" }}
        {...context}
        documentNote={documentNote}
      />
    );
    const trigger = container.querySelector<HTMLElement>("[tabindex='0']")!;
    expect(trigger).toHaveTextContent("…");
    expect(trigger).not.toHaveTextContent(documentNote);
    fireEvent.focus(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(documentNote);
    expect(container.querySelector("img")).toBeNull();
  });

  it("来源交货单号缺失时不编造单号", () => {
    render(
      <ExceptionEvidence exception={{ ...record, reason_code: "inbound_order_not_found" }} hasOverreceiptRule={false} />
    );
    expect(screen.getByText("来源文件未提供交货单号，请核对交货单号、SKU 和站点")).toBeInTheDocument();
  });

  it("未知原因保留原文并提示联系维护人员", () => {
    const exception = { ...record, reason_code: "unknown" as const, reason: "新原因 <script>" };
    const { container } = render(
      <>
        <ExceptionEvidence exception={exception} {...context} />
        <ReasonGuidance exception={exception} {...context} />
      </>
    );
    expect(screen.getAllByText("新原因 <script>：未登记的原因，请联系维护人员")).toHaveLength(2);
    expect(container.querySelector("script")).toBeNull();
    expect(getReasonDefinition("toString").actions).toEqual([]);
  });

  it("采购超量未启用规则及历史超收明细缺失时保留原展示", () => {
    const { rerender } = render(<ExceptionEvidence exception={record} hasOverreceiptRule={false} />);
    expect(screen.getByText("本批次未启用超收规则")).toBeInTheDocument();
    rerender(<ExceptionEvidence exception={{ ...record, reason_code: "overreceipt_limit_exceeded" }} {...context} />);
    expect(screen.getByText("历史批次暂无额度明细")).toBeInTheDocument();
  });
});
