import { act, fireEvent, render as renderComponent, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp, ConfigProvider, message as staticMessage } from "antd";
import { StrictMode } from "react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, AUTH_EXPIRED_EVENT, download } from "../../api";
import type { InputVersion } from "../../types";
import { InputDataPanel } from "./InputDataPanel";

function render(ui: ReactElement) {
  return renderComponent(ui, {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp message={{ top: 64 }}>{children}</AntApp>
      </ConfigProvider>
    )
  });
}

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, download: vi.fn() };
});

const versions: InputVersion[] = [
  {
    id: 1,
    kind: "purchase",
    name: "purchase-current",
    original_name: "purchase.xlsx",
    active: true,
    created_by: 1,
    created_at: "2026-07-21T09:00:00"
  },
  {
    id: 2,
    kind: "purchase",
    name: "purchase-old",
    original_name: "purchase-old.xlsx",
    active: false,
    created_by: 1,
    created_at: "2026-07-20T09:00:00"
  },
  {
    id: 3,
    kind: "position",
    name: "position-current",
    original_name: "position.xlsx",
    active: true,
    created_by: 2,
    created_at: "2026-07-21T10:00:00"
  },
  {
    id: 4,
    kind: "position",
    name: "position-old",
    original_name: "position-old.xlsx",
    active: false,
    created_by: 1,
    created_at: "2026-07-19T09:00:00"
  },
  {
    id: 5,
    kind: "supplier",
    name: "supplier-old",
    original_name: "supplier-old.xlsx",
    active: false,
    created_by: 1,
    created_at: "2026-07-18T09:00:00"
  },
  {
    id: 6,
    kind: "position",
    name: "position-older",
    original_name: "position-older.xlsx",
    active: false,
    created_by: 1,
    created_at: "2026-07-18T08:00:00"
  },
  {
    id: 7,
    kind: "product",
    name: "product-current",
    original_name: "product.xlsx",
    active: true,
    created_by: 1,
    created_at: "2026-07-21T11:00:00"
  },
  {
    id: 8,
    kind: "product",
    name: "product-old",
    original_name: "product-old.xlsx",
    active: false,
    created_by: 1,
    created_at: "2026-07-20T11:00:00"
  }
];

const jsonResponse = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });

let failInspection = false;
let failUpload = false;
let failActivation = false;
let emptyProductPreview = false;
let pendingUpload: Deferred<Response> | null = null;
let pendingActivation: Deferred<Response> | null = null;

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const getCatalogButton = (label: string) =>
  screen.getByRole("button", {
    name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`)
  });

async function confirmHistoryActivation() {
  fireEvent.click(screen.getByText(/版本记录/, { selector: ".ant-tabs-tab-btn > span" }));
  fireEvent.click(
    within(screen.getByText("product-old").closest("tr")!).getByText("启用", { selector: "button > span" })
  );
  fireEvent.click(await screen.findByText("确认启用", { selector: "button > span" }));
}

describe("InputDataPanel", () => {
  beforeEach(() => {
    failInspection = false;
    failUpload = false;
    failActivation = false;
    emptyProductPreview = false;
    pendingUpload = null;
    pendingActivation = null;
    vi.mocked(download).mockReset();
    vi.spyOn(staticMessage, "success");
    vi.spyOn(staticMessage, "error");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";

        if (url.endsWith("/api/input-versions/7/inspection")) {
          if (failInspection) return jsonResponse({ detail: "商品文件无法解析" }, 400);
          return jsonResponse({
            summary: {
              kind: "product",
              row_count: 1,
              columns: ["SKU", "店铺/站点", "已锁定", "需复核"],
              metrics: {},
              issues: []
            },
            preview: {
              kind: "product",
              columns: ["SKU", "店铺/站点", "已锁定", "需复核"],
              rows: emptyProductPreview
                ? []
                : [{ SKU: "PRODUCT-SKU", "店铺/站点": "SEEKWAY:US", 已锁定: true, 需复核: false }],
              total: emptyProductPreview ? 0 : 1,
              offset: 0,
              limit: 20
            }
          });
        }
        if (url.endsWith("/api/input-versions/5/inspection")) {
          return jsonResponse({
            summary: {
              kind: "supplier",
              row_count: 1,
              columns: ["供应商编号", "供应商名称", "状态", "供应商别名"],
              metrics: { aliases: 2, suppliers_with_aliases: 1 },
              issues: []
            },
            preview: {
              kind: "supplier",
              columns: ["供应商编号", "供应商名称", "状态", "供应商别名"],
              rows: [
                {
                  供应商编号: "SUPPLIER-GYS",
                  供应商名称: "RUIZY",
                  状态: "启用",
                  供应商别名: "瑞智雅|RIVBOS"
                }
              ],
              total: 1,
              offset: 0,
              limit: 20
            }
          });
        }
        if (url.endsWith("/api/input-versions/3/inspection")) {
          return jsonResponse({
            summary: {
              kind: "position",
              row_count: 1,
              columns: ["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位"],
              metrics: { sites: 1, skus: 1, mskus: 1 },
              issues: [
                {
                  severity: "warning",
                  code: "empty_stocking",
                  message: "备货定位不能为空",
                  row_numbers: [2, 3]
                }
              ]
            },
            preview: {
              kind: "position",
              columns: ["店铺-站点", "积加SKU", "MSKU"],
              rows: [{ "店铺-站点": "SEEKWAY:US", 积加SKU: "SKU-A", MSKU: "MSKU-A" }],
              total: 1,
              offset: 0,
              limit: 20
            }
          });
        }
        if (url.endsWith("/api/input-versions/product") && method === "POST") {
          if (failUpload) return jsonResponse({ detail: "输入版本校验失败：缺少 SKU" }, 400);
          if (pendingUpload) return pendingUpload.promise;
          return jsonResponse({ ...versions[6], id: 9, name: "product-replacement" }, 201);
        }
        if (url.endsWith("/api/input-versions/supplier") && method === "POST") {
          return jsonResponse(
            {
              detail: "输入版本校验失败：Excel 行 2, 3：供应商名称或别名会造成匹配歧义"
            },
            400
          );
        }
        if (url.endsWith("/api/input-versions/8/activate") && method === "POST") {
          if (failActivation) return jsonResponse({ detail: "合成版本启用失败" }, 400);
          if (pendingActivation) return pendingActivation.promise;
          return jsonResponse({ ...versions[7], active: true });
        }
        throw new Error(`Unexpected request: ${method} ${url}`);
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
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
    expect(screen.getAllByRole("button", { name: /，(已就绪|未启用)，/ })).toHaveLength(5);
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
    expect(drawer.querySelector(".input-data-maintenance-header")).toHaveStyle({
      borderColor: "#e2e9e7",
      background: "#f7f9f8"
    });
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
    failInspection = true;
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );
    expect(await screen.findByText("商品文件无法解析")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /质量检查/ }));
    expect(screen.getByText("等待检查结果。")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/7/inspection"))).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: /数据预览/ }));
    failInspection = false;
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

  it("shows supplier alias conflict rows returned by upload validation", async () => {
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
    await screen.findByText("瑞智雅|RIVBOS");
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "supplier-conflict" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(fileInput, {
      target: { files: [new File(["excel"], "supplier.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("supplier.xlsx");
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    expect(await screen.findByText(/Excel 行 2, 3.*匹配歧义/)).toBeInTheDocument();
  });

  it("renders boolean preview values explicitly", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    expect(await screen.findByText("是")).toBeInTheDocument();
    expect(screen.getByText("否")).toBeInTheDocument();
  });

  it("exposes the selected catalog item, readiness, and current version to assistive technology", () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    const productButton = getCatalogButton("商品信息");
    const supplierButton = getCatalogButton("供应商资料");
    expect(productButton).toHaveAttribute("aria-pressed", "true");
    expect(productButton).toHaveAccessibleName("商品信息，已就绪，当前版本 product-current");
    expect(supplierButton).toHaveAttribute("aria-pressed", "false");
    expect(supplierButton).toHaveAccessibleName("供应商资料，未启用，等待上传");

    fireEvent.click(supplierButton);
    expect(productButton).toHaveAttribute("aria-pressed", "false");
    expect(supplierButton).toHaveAttribute("aria-pressed", "true");
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

  it("shows no-active and empty-preview states without requesting inactive versions", async () => {
    emptyProductPreview = true;
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

  it("uploads a replacement only after explicit confirmation", async () => {
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    await screen.findByText("PRODUCT-SKU");
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "product-replacement" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: { files: [new File(["excel"], "replacement.xlsx", { type: "application/vnd.ms-excel" })] }
    });

    expect(await screen.findByText("replacement.xlsx")).toBeInTheDocument();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
        )
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    await waitFor(() => {
      expect(onVersionsChanged).toHaveBeenCalledOnce();
    });
    const uploadCall = vi
      .mocked(fetch)
      .mock.calls.find(
        ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
      );
    expect(uploadCall).toBeDefined();
    const body = uploadCall?.[1]?.body as FormData;
    expect(body.get("name")).toBe("product-replacement");
    expect(body.get("activate")).toBe("true");
    expect(body.get("file")).toBeInstanceOf(File);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    const feedback = await screen.findByText("商品信息已上传并启用，将用于新批次");
    expect(screen.getAllByText(feedback.textContent!)).toHaveLength(1);
    expect(feedback.closest<HTMLElement>(".ant-message")?.style.getPropertyValue("--notification-top")).toBe("64px");
    expect(staticMessage.success).not.toHaveBeenCalled();
  });

  it.each(["success", "failure", "pending"])(
    "preserves history activation feedback and locking with outcome=%s",
    async (outcome) => {
      const failed = outcome === "failure";
      failActivation = failed;
      const response = outcome === "pending" ? createDeferred<Response>() : null;
      pendingActivation = response;
      const onVersionsChanged = vi.fn();
      render(
        <InputDataPanel
          versions={versions}
          loading={false}
          onVersionsChanged={onVersionsChanged}
          onOpenPositionDraft={vi.fn()}
        />
      );
      fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
      const historyRow = screen.getByText("product-old").closest("tr")!;
      const activateButton = within(historyRow).getByRole("button", { name: "启用" });
      fireEvent.click(activateButton);
      expect(onVersionsChanged).not.toHaveBeenCalled();
      fireEvent.click(await screen.findByRole("button", { name: "确认启用" }));

      if (response) {
        await waitFor(() => expect(activateButton).toBeDisabled());
        expect(activateButton).toHaveAttribute("aria-busy", "true");
        expect(getCatalogButton("供应商资料")).toBeDisabled();
        expect(onVersionsChanged).not.toHaveBeenCalled();
        fireEvent.click(activateButton);
        expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
        response.resolve(jsonResponse({ ...versions[7], active: true }));
      }

      const successText = "product-old 已启用，将用于新批次";
      if (failed) {
        expect(await screen.findByText("合成版本启用失败")).toBeInTheDocument();
        expect(onVersionsChanged).not.toHaveBeenCalled();
        expect(screen.queryByText(successText)).not.toBeInTheDocument();
        expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
      } else {
        const feedback = await screen.findByText(successText);
        expect(onVersionsChanged).toHaveBeenCalledOnce();
        expect(screen.getAllByText(successText)).toHaveLength(1);
        expect(feedback.closest<HTMLElement>(".ant-message")?.style.getPropertyValue("--notification-top")).toBe(
          "64px"
        );
      }
      expect(staticMessage.success).not.toHaveBeenCalled();
      expect(staticMessage.error).not.toHaveBeenCalled();
      expect(
        vi
          .mocked(fetch)
          .mock.calls.filter(
            ([input, init]) => String(input).endsWith("/api/input-versions/8/activate") && init?.method === "POST"
          )
      ).toHaveLength(1);
      await waitFor(() => expect(activateButton).toBeEnabled());
      expect(getCatalogButton("供应商资料")).toBeEnabled();
    },
    30_000
  );

  it("locks type switching and duplicate upload submission while an upload is pending", async () => {
    pendingUpload = createDeferred<Response>();
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    await screen.findByText("PRODUCT-SKU");
    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    const supplierButton = getCatalogButton("供应商资料");
    // 单独检查可见性和隐藏祖先，避免角色查询重复计算深层表格按钮的样式。
    const historyActivateButton = within(screen.getByText("product-old").closest("tr")!).getByRole("button", {
      name: "启用",
      hidden: true
    });
    expect(historyActivateButton).toBeVisible();
    expect(historyActivateButton.closest('[hidden], [aria-hidden="true"]')).toBeNull();
    const status = within(screen.getByRole("region", { name: "商品信息资料状态" }));
    const updateButton = status.getByRole("button", { name: "更新资料" });
    fireEvent.click(updateButton);
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "product-slow" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(fileInput, {
      target: { files: [new File(["first"], "first.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("first.xlsx");
    const submitButton = screen.getByRole("button", { name: "校验并启用新版本" });
    try {
      submitButton.click();
      await waitFor(() => {
        expect(
          vi
            .mocked(fetch)
            .mock.calls.filter(
              ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
            )
        ).toHaveLength(1);
      });
      expect(supplierButton).toBeDisabled();
      const currentFileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
      expect(currentFileInput).toBeDisabled();
      expect(submitButton).toBeDisabled();
      expect(submitButton).toHaveAttribute("aria-busy", "true");
      expect(historyActivateButton).toBeDisabled();

      fireEvent.change(currentFileInput, {
        target: { files: [new File(["second"], "second.xlsx", { type: "application/vnd.ms-excel" })] }
      });
      expect(
        vi
          .mocked(fetch)
          .mock.calls.filter(
            ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
          )
      ).toHaveLength(1);
    } finally {
      pendingUpload?.resolve(jsonResponse({ ...versions[6], id: 9, name: "product-slow" }, 201));
    }

    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    expect(supplierButton).toBeEnabled();
  }, 30_000);

  it.each([false, true])("does not upload when the name or file is missing, hasName=%s", async (hasName) => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    if (hasName) {
      fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "synthetic-no-file" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));
    expect(await screen.findByText(hasName ? "请选择要上传的 Excel 文件" : "请输入版本名称")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
    if (hasName) expect(screen.getByLabelText("新版本名称")).toHaveValue("synthetic-no-file");
  });

  it("downloads the current file from the selected-type status header", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    fireEvent.click(screen.getByRole("button", { name: "下载当前文件" }));
    await waitFor(() => {
      expect(download).toHaveBeenCalledWith("/api/input-versions/7/download", "product.xlsx");
    });
  });

  it.each(["upload", "activate"])(
    "does not report %s success when the saved list cannot refresh",
    async (operation) => {
      const onVersionsChanged = vi.fn().mockResolvedValue(false);
      render(
        <InputDataPanel
          versions={versions}
          loading={false}
          onVersionsChanged={onVersionsChanged}
          onOpenPositionDraft={vi.fn()}
        />
      );
      await screen.findByText("PRODUCT-SKU");
      if (operation === "upload") {
        fireEvent.click(screen.getByText("更新资料", { selector: "button > span" }));
        fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "saved-version" } });
        fireEvent.change(document.querySelector('input[type="file"]')!, {
          target: { files: [new File(["synthetic"], "saved.xlsx")] }
        });
        await screen.findByText("saved.xlsx");
        fireEvent.click(screen.getByText("校验并启用新版本", { selector: "button > span" }));
      } else {
        await confirmHistoryActivation();
      }
      await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
      await waitFor(() => expect(getCatalogButton("供应商资料")).toBeEnabled());
      expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
      expect(screen.queryByText("上传失败")).not.toBeInTheDocument();
      if (operation === "upload") {
        expect(screen.queryByLabelText("新版本名称")).not.toBeInTheDocument();
        fireEvent.click(screen.getByText("更新资料", { selector: "button > span" }));
        expect(screen.getByLabelText("新版本名称")).toHaveValue("");
        expect(screen.queryByText("saved.xlsx")).not.toBeInTheDocument();
      }
      expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    }
  );

  it.each(["inspection", "upload", "activate", "download"])(
    "does not append local feedback for %s 401",
    async (operation) => {
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ id: 1 }));
      await api("/api/auth/me");
      const expired = vi.fn();
      window.addEventListener(AUTH_EXPIRED_EVENT, expired);
      const originalFetch = vi.mocked(fetch).getMockImplementation()!;
      vi.mocked(fetch).mockImplementation((input, init) => {
        if (operation === "inspection" || init?.method === "POST")
          return Promise.resolve(jsonResponse({ detail: "合成未登录" }, 401));
        return originalFetch(input, init);
      });
      vi.mocked(download).mockRejectedValue(new ApiError(401, "合成未登录"));
      const onVersionsChanged = vi.fn();
      try {
        render(
          <InputDataPanel
            versions={versions}
            loading={false}
            onVersionsChanged={onVersionsChanged}
            onOpenPositionDraft={vi.fn()}
          />
        );
        if (operation !== "inspection") await screen.findByText("PRODUCT-SKU");
        if (operation === "upload") {
          fireEvent.click(screen.getByText("更新资料", { selector: "button > span" }));
          fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "retry-version" } });
          fireEvent.change(document.querySelector('input[type="file"]')!, {
            target: { files: [new File(["synthetic"], "retry.xlsx")] }
          });
          await screen.findByText("retry.xlsx");
          fireEvent.click(screen.getByText("校验并启用新版本", { selector: "button > span" }));
        } else if (operation === "activate") {
          await confirmHistoryActivation();
        } else if (operation === "download") {
          fireEvent.click(screen.getByText("下载当前文件", { selector: "button > span" }));
          await waitFor(() => expect(download).toHaveBeenCalledOnce());
        }
        if (operation !== "download") await waitFor(() => expect(expired).toHaveBeenCalledOnce());
        await waitFor(() => expect(getCatalogButton("供应商资料")).toBeEnabled());
        expect(screen.queryByText("合成未登录")).not.toBeInTheDocument();
        expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
        expect(onVersionsChanged).not.toHaveBeenCalled();
        if (operation === "upload") expect(screen.getByLabelText("新版本名称")).toHaveValue("retry-version");
      } finally {
        window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
      }
    }
  );

  it("surfaces inspection and upload failures", async () => {
    failInspection = true;
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByText("无法读取当前版本内容")).toBeInTheDocument();
    expect(screen.getByText("商品文件无法解析")).toBeInTheDocument();

    failUpload = true;
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "broken-product" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(fileInput!, {
      target: { files: [new File(["broken"], "broken.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("broken.xlsx");
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    expect(await screen.findByText("输入版本校验失败：缺少 SKU")).toBeInTheDocument();
    expect(onVersionsChanged).not.toHaveBeenCalled();
    const feedback = await screen.findByText("上传失败，请检查页面提示");
    expect(screen.getAllByText("上传失败，请检查页面提示")).toHaveLength(1);
    expect(feedback.closest<HTMLElement>(".ant-message")?.style.getPropertyValue("--notification-top")).toBe("64px");
    expect(staticMessage.error).not.toHaveBeenCalled();
    expect(screen.getByLabelText("新版本名称")).toHaveValue("broken-product");
    expect(screen.getByText("broken.xlsx")).toBeInTheDocument();

    fireEvent.click(getCatalogButton("供应商资料"));
    expect(screen.queryByText("输入版本校验失败：缺少 SKU")).not.toBeInTheDocument();
    fireEvent.click(getCatalogButton("商品信息"));
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    expect(screen.getByText("输入版本校验失败：缺少 SKU")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "synthetic-retry" } });
    const retryFileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(retryFileInput, { target: { files: [new File(["replacement"], "replacement.xlsx")] } });
    await screen.findByText("replacement.xlsx");
    expect(screen.queryByText("输入版本校验失败：缺少 SKU")).not.toBeInTheDocument();
    expect(screen.queryByText("broken.xlsx")).not.toBeInTheDocument();
    failUpload = false;
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));
    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
