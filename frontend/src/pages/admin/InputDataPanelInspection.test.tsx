import { render, setupInputDataPanelTests, versions, getCatalogButton } from "./inputDataPanelTestSupport";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";

import { jsonResponse, deferred as createDeferred } from "./positionDraftTestSupport";
import { InputDataPanel } from "./InputDataPanel";

const state = setupInputDataPanelTests();

describe("InputDataPanel 检查缓存与预览", () => {
  it("requests inspection data only for the selected active versions", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(await screen.findByText("PRODUCT-SKU")).toBeInTheDocument();
    fireEvent.click(getCatalogButton("MSKU定位"));
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();

    const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls).toContain("/api/input-versions/7/inspection");
    expect(requestedUrls).toContain("/api/input-versions/3/inspection");
    expect(requestedUrls.some((url) => url.endsWith("/summary"))).toBe(false);
    expect(requestedUrls.some((url) => url.endsWith("/preview"))).toBe(false);
    expect(requestedUrls.some((url) => url.includes("/1/"))).toBe(false);
    expect(requestedUrls.some((url) => url.includes("/2/"))).toBe(false);
    expect(requestedUrls.some((url) => url.includes("/4/"))).toBe(false);
  });
  it("reuses loaded product, supplier, and position inspections", async () => {
    const versionsWithSupplier = versions.map((version) =>
      version.id === 5 ? { ...version, name: "supplier-current", active: true } : version
    );
    render(
      <InputDataPanel
        versions={versionsWithSupplier}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByText("PRODUCT-SKU")).toBeInTheDocument();
    fireEvent.click(getCatalogButton("供应商资料"));
    expect(await screen.findByText("SUPPLIER-GYS")).toBeInTheDocument();
    fireEvent.click(getCatalogButton("MSKU定位"));
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();

    fireEvent.click(getCatalogButton("商品信息"));
    expect(screen.getByText("PRODUCT-SKU")).toBeInTheDocument();
    fireEvent.click(getCatalogButton("供应商资料"));
    expect(screen.getByText("SUPPLIER-GYS")).toBeInTheDocument();

    for (const versionId of [7, 5, 3]) {
      expect(
        vi
          .mocked(fetch)
          .mock.calls.filter(([input]) => String(input).endsWith(`/api/input-versions/${versionId}/inspection`))
      ).toHaveLength(1);
    }
  });
  it.each([false, true])(
    "deduplicates pending inspection and ignores late results for another kind with failure=%s",
    async (failed) => {
      const originalFetch = vi.mocked(fetch).getMockImplementation()!;
      const productResponse = await originalFetch("/api/input-versions/7/inspection");
      const response = createDeferred<Response>();
      vi.mocked(fetch).mockImplementation((input, init) =>
        String(input).endsWith("/api/input-versions/7/inspection") ? response.promise : originalFetch(input, init)
      );
      render(
        <StrictMode>
          <InputDataPanel
            versions={versions}
            loading={false}
            onVersionsChanged={vi.fn()}
            onOpenPositionDraft={vi.fn()}
          />
        </StrictMode>
      );
      expect(await screen.findByText("读取摘要与预览")).toBeInTheDocument();
      fireEvent.click(getCatalogButton("MSKU定位"));
      expect(await screen.findByText("SKU-A")).toBeInTheDocument();
      fireEvent.click(getCatalogButton("商品信息"));
      expect(await screen.findByText("读取摘要与预览")).toBeInTheDocument();
      fireEvent.click(getCatalogButton("MSKU定位"));
      expect(await screen.findByText("SKU-A")).toBeInTheDocument();
      await act(async () => {
        response.resolve(failed ? jsonResponse({ detail: "合成晚返回失败" }, 400) : productResponse);
        await response.promise;
      });
      expect(screen.getByText("SKU-A")).toBeInTheDocument();
      expect(screen.queryByText("PRODUCT-SKU")).not.toBeInTheDocument();
      expect(screen.queryByText("合成晚返回失败")).not.toBeInTheDocument();
      if (!failed) {
        fireEvent.click(getCatalogButton("商品信息"));
        expect(await screen.findByText("PRODUCT-SKU")).toBeInTheDocument();
      }
      for (const id of [7, 3]) {
        expect(
          vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith(`/${id}/inspection`))
        ).toHaveLength(1);
      }
    },
    30_000
  );
  it("retries a failed inspection once and reuses the successful result across tabs", async () => {
    state.failInspection = true;
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );
    expect(await screen.findByText("商品文件无法解析")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /质量检查/ }));
    expect(screen.getByText("等待检查结果。")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/7/inspection"))).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: /数据预览/ }));
    state.failInspection = false;
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("PRODUCT-SKU")).toBeInTheDocument();
    expect(screen.queryByText("商品文件无法解析")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    fireEvent.click(screen.getByRole("tab", { name: /质量检查/ }));
    expect(screen.getByText("文件结构已通过校验，当前未执行内容质量诊断")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /数据预览/ }));
    expect(screen.getByText("PRODUCT-SKU")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/7/inspection"))).toHaveLength(2);
  }, 30_000);
  it("keeps quality row counts, tab totals and cached results consistent when switching kinds", async () => {
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const response = await originalFetch(input, init);
      if (!String(input).endsWith("/3/inspection")) return response;
      const inspection = await response.json();
      inspection.summary.issues = [
        { severity: "error", code: "missing", message: "合成缺失", row_numbers: [2, 3] },
        { severity: "error", code: "conflict", message: "合成冲突", row_numbers: [2] },
        { severity: "warning", code: "global", message: "合成全表提醒", row_numbers: [] }
      ];
      return jsonResponse(inspection);
    });
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );
    fireEvent.click(getCatalogButton("MSKU定位"));
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "质量检查 4" }));
    const quality = within(screen.getByRole("region", { name: "质量检查" }));
    expect(quality.getByText("3 个错误")).toBeInTheDocument();
    expect(quality.getByText("1 个警告")).toBeInTheDocument();
    expect(quality.getByText("涉及 Excel 行：2、3")).toBeInTheDocument();
    expect(quality.getByText("涉及 Excel 行：2")).toBeInTheDocument();
    expect(quality.queryByText("全表")).not.toBeInTheDocument();
    fireEvent.click(getCatalogButton("商品信息"));
    expect(await screen.findByText("PRODUCT-SKU")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "质量检查 0" }));
    expect(screen.getByText("文件结构已通过校验，当前未执行内容质量诊断")).toBeInTheDocument();
    expect(screen.queryByText("合成冲突")).not.toBeInTheDocument();
    fireEvent.click(getCatalogButton("MSKU定位"));
    fireEvent.click(screen.getByRole("tab", { name: "质量检查 4" }));
    expect(screen.getByText("3 个错误")).toBeInTheDocument();
    for (const id of [7, 3]) {
      expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith(`/${id}/inspection`))).toHaveLength(
        1
      );
    }
  });
  it("shows supplier alias format, metrics, preview, and quality result", async () => {
    const versionsWithSupplier = versions.map((version) => (version.id === 5 ? { ...version, active: true } : version));
    render(
      <InputDataPanel
        versions={versionsWithSupplier}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(getCatalogButton("供应商资料"));

    expect(await screen.findByText("瑞智雅|RIVBOS")).toBeInTheDocument();
    expect(screen.getByText("2 个别名")).toBeInTheDocument();
    expect(screen.getByText("1 个供应商已配置别名")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看字段说明" }));
    expect(screen.getByText("供应商别名（多个别名用 | 分隔）")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /质量检查/ }));
    expect(screen.getByText("未发现资料质量问题")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    expect(screen.getByText("供应商别名为可选列")).toBeInTheDocument();
    expect(screen.getByText("供应商别名为可选列").closest('[role="alert"]')).toHaveStyle({ borderRadius: "8px" });
    expect(screen.getByText(/名称或别名相同、互为子串/)).toBeInTheDocument();
  });
  it("renders boolean preview values explicitly", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(await screen.findByText("是")).toBeInTheDocument();
    expect(screen.getByText("否")).toBeInTheDocument();
  });
  it("shows no-active and empty-preview states without requesting inactive versions", async () => {
    state.emptyProductPreview = true;
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(await screen.findByText("当前版本没有可预览的数据")).toBeInTheDocument();
    fireEvent.click(getCatalogButton("供应商资料"));
    expect(await screen.findByText("供应商资料尚无启用版本")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    expect(screen.getByText("supplier-old")).toBeInTheDocument();

    const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls.some((url) => url.includes("/5/"))).toBe(false);
  });
});
