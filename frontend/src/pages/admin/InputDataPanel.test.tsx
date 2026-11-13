import { render, setupInputDataPanelTests, versions, getCatalogButton } from "./inputDataPanelTestSupport";
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InputDataPanel } from "./InputDataPanel";

setupInputDataPanelTests();

describe("InputDataPanel 资料类型与工作区", () => {
  it.each([true, false])("采购资料仅维护仓库和模板，忽略旧映射和未知类型（启用=%s）", (active) => {
    const legacyVersions = ["purchase_mapping", "unknown_kind"].map((kind, index) => ({
      ...versions[6],
      id: 91 + index,
      kind,
      name: `旧资料-${kind}`,
      active
    }));
    render(
      <InputDataPanel
        versions={legacyVersions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );
    expect(screen.getByText("0/5 已启用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "采购单录入资料" }));
    expect(screen.getByRole("heading", { name: "采购仓库" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^采购仓库，/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^采购单录入模板，/ })).toBeInTheDocument();
    expect(screen.queryByText("采购站点映射")).not.toBeInTheDocument();
    expect(screen.queryByText(/旧资料-/)).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /^商品信息，/ })).not.toBeInTheDocument();
    expect(screen.getByText("0/2 已启用")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    expect(screen.getByText("暂无采购仓库版本")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: "基础资料" }));
    expect(screen.getByRole("heading", { name: "商品信息" })).toBeInTheDocument();
  });
  it("商品字段说明保留原必填列并列出国家和 MSKU 为可选字段", () => {
    render(<InputDataPanel versions={[]} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "查看字段说明" }));
    const fields = screen.getByRole("region", { name: "字段说明" });
    expect(within(fields).getByText("可选字段")).toBeInTheDocument();
    for (const field of ["SKU", "店铺/站点", "品类A", "锁仓MKSU", "国家", "MSKU"]) {
      expect(within(fields).getByText(field)).toBeInTheDocument();
    }
  });
  it("shows a type-specific position explanation, metrics, preview, and maintenance entry", async () => {
    const onOpenPositionDraft = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={onOpenPositionDraft}
      />
    );

    fireEvent.click(getCatalogButton("MSKU定位"));

    expect(await screen.findByText("仅用于补充待处理导出的定位信息")).toBeInTheDocument();
    expect(await screen.findByText("1 个站点")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /质量检查/ }));
    expect(screen.getByText("2 个警告")).toBeInTheDocument();
    expect(screen.getByText("备货定位不能为空")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /数据预览/ }));
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    expect(onOpenPositionDraft).toHaveBeenCalledOnce();
  });
  it("keeps maintainable input kinds in one horizontal switcher above the workspace", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(await screen.findByText("PRODUCT-SKU")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "基础资料类型" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "公共基础资料" })).not.toBeInTheDocument();
    expect(screen.getByText("2/5 已启用")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "商品信息资料状态" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio", { name: /，(已就绪|未启用)，/ })).toHaveLength(5);
    expect(screen.getByRole("tab", { name: /数据预览/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /版本记录/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /质量检查/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "商品信息数据预览" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "商品信息版本记录" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Excel 行" })).toBeInTheDocument();
    expect(screen.queryByLabelText("新版本名称")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    expect(screen.getByRole("table", { name: "商品信息版本记录" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    const drawer = screen.getByRole("dialog", { name: "更新商品信息" });
    const header = drawer.querySelector<HTMLElement>(".input-data-maintenance-header");
    expect(header).toHaveStyle({ borderColor: "#e2e9e7" });
    // 计算样式会解析 CSS 变量，这里核对组件写入的原始变量引用。
    expect(header?.style.background).toBe("var(--dn-surface-muted)");
    expect(drawer.querySelector(".input-data-maintenance-body")).toHaveStyle({ padding: "22px 24px" });
    expect(screen.getByLabelText("新版本名称")).toBeInTheDocument();
  });
  it("keeps purchase data entirely out of administrator maintenance", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(await screen.findByRole("heading", { name: "商品信息" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^采购需求/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "采购需求" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "积加采购数据同步" })).not.toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/api/input-versions/1/inspection"))
    ).toBe(false);
  });
  it("routes position replacements and history activation through web maintenance", async () => {
    const onOpenPositionDraft = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={onOpenPositionDraft}
      />
    );

    fireEvent.click(getCatalogButton("MSKU定位"));
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "更新资料" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    expect(
      within(screen.getByText("position-old").closest("tr")!).queryByRole("button", { name: "启用" })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    expect(onOpenPositionDraft).toHaveBeenCalledOnce();
  });
  it("explains the real impact of all five maintainable input kinds", () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    const expectations = [
      ["商品信息", "锁仓标识用于解决同一 SKU、站点的歧义"],
      ["供应商资料", "未能唯一识别供应商会导致批次预检失败，需修正供应商资料或交货文件名后重试"],
      ["MSKU定位", "不参与采购余额扣减或仓库分配"],
      ["导出模板", "必须保持既有七列导出格式兼容"],
      ["积加入库模板", "不影响原交货处理的 A:G 导出模板"]
    ];

    for (const [label, impact] of expectations) {
      fireEvent.click(getCatalogButton(label));
      fireEvent.click(screen.getByRole("button", { name: "查看字段说明" }));
      expect(screen.getByText(new RegExp(impact))).toBeInTheDocument();
    }
  });
  it("keeps the reference explanation compact and resets it for a new type", () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(screen.queryByText(/锁仓标识用于解决同一 SKU、站点的歧义/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看字段说明" }));
    expect(screen.getByText(/锁仓标识用于解决同一 SKU、站点的歧义/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "收起字段说明" }));
    expect(screen.queryByText(/锁仓标识用于解决同一 SKU、站点的歧义/)).not.toBeInTheDocument();

    fireEvent.click(getCatalogButton("供应商资料"));
    expect(screen.queryByText(/未能唯一识别供应商会导致批次预检失败/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看字段说明" }));
    expect(screen.getByText(/未能唯一识别供应商会导致批次预检失败/)).toBeInTheDocument();
  });
  it("exposes the selected catalog item, readiness, and current version to assistive technology", () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    const productButton = getCatalogButton("商品信息");
    const supplierButton = getCatalogButton("供应商资料");
    expect(productButton).toBeChecked();
    expect(productButton).toHaveAccessibleName("商品信息，已就绪，当前版本 product-current");
    expect(supplierButton).not.toBeChecked();
    expect(supplierButton).toHaveAccessibleName("供应商资料，未启用，等待上传");

    fireEvent.click(supplierButton);
    expect(productButton).not.toBeChecked();
    expect(supplierButton).toBeChecked();
  });
  it("keeps the current data status concise and moves repeated details out of the header", () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    const status = screen.getByRole("region", { name: "商品信息资料状态" });
    expect(within(status).getByRole("heading", { name: "商品信息" })).toBeInTheDocument();
    expect(within(status).getByText("已启用")).toBeInTheDocument();
    expect(within(status).getByText("版本 product-current")).toBeInTheDocument();
    expect(within(status).getByText("product.xlsx")).toBeInTheDocument();
    expect(within(status).getByText(/更新于/)).toBeInTheDocument();
    expect(within(status).queryByText("当前资料")).not.toBeInTheDocument();
    expect(within(status).queryByText("数据量")).not.toBeInTheDocument();
    expect(within(status).queryByText("创建人")).not.toBeInTheDocument();
  });
});
