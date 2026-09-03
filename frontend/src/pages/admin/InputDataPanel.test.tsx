import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { download } from "../../api";
import type { InputVersion } from "../../types";
import { InputDataPanel } from "./InputDataPanel";

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

const jsonResponse = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "Content-Type": "application/json" }
});

let failInspection = false;
let failUpload = false;
let emptyProductPreview = false;
let pendingUpload: Deferred<Response> | null = null;

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

const getCatalogButton = (label: string) => screen.getByRole("button", {
  name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`)
});

describe("InputDataPanel", () => {
  beforeEach(() => {
    failInspection = false;
    failUpload = false;
    emptyProductPreview = false;
    pendingUpload = null;
    vi.mocked(download).mockReset();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
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
            rows: emptyProductPreview ? [] : [{ SKU: "PRODUCT-SKU", "店铺/站点": "SEEKWAY:US", 已锁定: true, 需复核: false }],
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
            columns: ["供应商编号", "供应商名称", "状态"],
            metrics: {},
            issues: []
          },
          preview: {
            kind: "supplier",
            columns: ["供应商编号", "供应商名称", "状态"],
            rows: [{ 供应商编号: "SUPPLIER-GYS", 供应商名称: "测试供应商", 状态: "启用" }],
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
            columns: ["店铺-站点", "积加SKU", "MSKU", "规模定位", "备货定位", "已下单可售天数"],
            metrics: { sites: 1, skus: 1, mskus: 1 },
            issues: [{
              severity: "warning",
              code: "empty_stocking",
              message: "备货定位不能为空",
              row_numbers: [2, 3]
            }]
          },
          preview: {
            kind: "position",
            columns: ["店铺-站点", "积加SKU", "MSKU"],
            rows: [{ "店铺-站点": "SEEKWAY:US", "积加SKU": "SKU-A", MSKU: "MSKU-A" }],
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
      if (url.endsWith("/api/input-versions/2/activate") && method === "POST") {
        return jsonResponse({ ...versions[1], active: true });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
    expect(screen.getByRole("dialog", { name: "更新商品信息" })).toBeInTheDocument();
    expect(screen.getByLabelText("新版本名称")).toBeInTheDocument();
  });

  it("keeps purchase data entirely out of administrator maintenance", async () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByRole("heading", { name: "商品信息" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^采购需求/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "采购需求" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "积加采购数据同步" })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) =>
      String(input).endsWith("/api/input-versions/1/inspection")
    )).toBe(false);
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
    expect(within(screen.getByText("position-old").closest("tr")!).queryByRole("button", { name: "启用" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    expect(onOpenPositionDraft).toHaveBeenCalledOnce();
  });

  it("explains the real impact of all five maintainable input kinds", () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
      version.id === 5
        ? { ...version, name: "supplier-current", active: true }
        : version
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
      expect(vi.mocked(fetch).mock.calls.filter(([input]) =>
        String(input).endsWith(`/api/input-versions/${versionId}/inspection`)
      )).toHaveLength(1);
    }
  });

  it("renders boolean preview values explicitly", async () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByText("是")).toBeInTheDocument();
    expect(screen.getByText("否")).toBeInTheDocument();
  });

  it("exposes the selected catalog item, readiness, and current version to assistive technology", () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
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
    expect(vi.mocked(fetch).mock.calls.some(([input, init]) =>
      String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
    )).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    await waitFor(() => {
      expect(onVersionsChanged).toHaveBeenCalledOnce();
    });
    const uploadCall = vi.mocked(fetch).mock.calls.find(([input, init]) =>
      String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
    );
    expect(uploadCall).toBeDefined();
    const body = uploadCall?.[1]?.body as FormData;
    expect(body.get("name")).toBe("product-replacement");
    expect(body.get("activate")).toBe("true");
    expect(body.get("file")).toBeInstanceOf(File);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

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
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "product-slow" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(fileInput, {
      target: { files: [new File(["first"], "first.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("first.xlsx");
    try {
      screen.getByRole("button", { name: "校验并启用新版本" }).click();
      await waitFor(() => {
        expect(vi.mocked(fetch).mock.calls.filter(([input, init]) =>
          String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
        )).toHaveLength(1);
      });
      expect(getCatalogButton("供应商资料")).toBeDisabled();
      const currentFileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
      expect(currentFileInput).toBeDisabled();
      expect(screen.getByRole("button", { name: "校验并启用新版本" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "校验并启用新版本" })).toHaveAttribute("aria-busy", "true");
      expect(within(screen.getByText("product-old").closest("tr")!).getByRole("button", { name: "启用" })).toBeDisabled();

      fireEvent.change(currentFileInput, {
        target: { files: [new File(["second"], "second.xlsx", { type: "application/vnd.ms-excel" })] }
      });
      expect(vi.mocked(fetch).mock.calls.filter(([input, init]) =>
        String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
      )).toHaveLength(1);
    } finally {
      pendingUpload?.resolve(jsonResponse({ ...versions[6], id: 9, name: "product-slow" }, 201));
    }

    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    expect(getCatalogButton("供应商资料")).toBeEnabled();
  }, 30_000);

  it("downloads the current file from the selected-type status header", async () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "下载当前文件" }));
    await waitFor(() => {
      expect(download).toHaveBeenCalledWith("/api/input-versions/7/download", "product.xlsx");
    });
  });

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

    fireEvent.click(getCatalogButton("供应商资料"));
    expect(screen.queryByText("输入版本校验失败：缺少 SKU")).not.toBeInTheDocument();
    fireEvent.click(getCatalogButton("商品信息"));
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    expect(screen.getByText("输入版本校验失败：缺少 SKU")).toBeInTheDocument();
  });
});
