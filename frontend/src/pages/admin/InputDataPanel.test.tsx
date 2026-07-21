import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  }
];

const jsonResponse = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "Content-Type": "application/json" }
});

let failInspection = false;
let failUpload = false;
let emptyPurchasePreview = false;
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

const getCatalogButton = (label: string) => screen.getByRole("button", {
  name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`)
});

describe("InputDataPanel", () => {
  beforeEach(() => {
    failInspection = false;
    failUpload = false;
    emptyPurchasePreview = false;
    pendingUpload = null;
    pendingActivation = null;
    vi.mocked(download).mockReset();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.endsWith("/api/input-versions/1/summary")) {
        if (failInspection) return jsonResponse({ detail: "采购文件无法解析" }, 400);
        return jsonResponse({
          kind: "purchase",
          row_count: 2,
          columns: ["SKU", "未交量"],
          metrics: {},
          issues: []
        });
      }
      if (url.endsWith("/api/input-versions/1/preview")) {
        return jsonResponse({
          kind: "purchase",
          columns: ["SKU", "未交量", "已锁定", "需复核"],
          rows: emptyPurchasePreview ? [] : [{ SKU: "PURCHASE-SKU", 未交量: 100, 已锁定: true, 需复核: false }],
          total: emptyPurchasePreview ? 0 : 1,
          offset: 0,
          limit: 50
        });
      }
      if (url.endsWith("/api/input-versions/3/summary")) {
        return jsonResponse({
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
        });
      }
      if (url.endsWith("/api/input-versions/3/preview")) {
        return jsonResponse({
          kind: "position",
          columns: ["店铺-站点", "积加SKU", "MSKU"],
          rows: [{ "店铺-站点": "SEEKWAY:US", "积加SKU": "SKU-A", MSKU: "MSKU-A" }],
          total: 1,
          offset: 0,
          limit: 50
        });
      }
      if (url.endsWith("/api/input-versions/position") && method === "POST") {
        if (failUpload) return jsonResponse({ detail: "输入版本校验失败：缺少 MSKU_视图" }, 400);
        if (pendingUpload) return pendingUpload.promise;
        return jsonResponse({ ...versions[2], id: 7, name: "position-replacement" }, 201);
      }
      if (url.endsWith("/api/input-versions/4/activate") && method === "POST") {
        if (pendingActivation) return pendingActivation.promise;
        return jsonResponse({ ...versions[3], active: true });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
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

    fireEvent.click(getCatalogButton("库位/排仓数据"));

    expect(await screen.findByText("仅用于补充待处理导出的定位信息")).toBeInTheDocument();
    expect(await screen.findByText("1 个站点")).toBeInTheDocument();
    expect(screen.getByText("2 个警告")).toBeInTheDocument();
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();
    expect(screen.getByText("备货定位不能为空")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    expect(onOpenPositionDraft).toHaveBeenCalledOnce();
  });

  it("explains the real impact of all five input kinds", () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    const expectations = [
      ["采购需求", "同批次文件按用户顺序连续消耗采购余额"],
      ["商品信息", "锁仓标识用于解决同一 SKU、站点的歧义"],
      ["供应商资料", "未能唯一识别供应商会导致批次预检失败，需修正供应商资料或交货文件名后重试"],
      ["库位/排仓数据", "不参与采购余额扣减或仓库分配"],
      ["导出模板", "必须保持既有七列导出格式兼容"]
    ];

    for (const [label, impact] of expectations) {
      fireEvent.click(getCatalogButton(label));
      expect(screen.getByText(new RegExp(impact))).toBeInTheDocument();
    }
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

    expect(await screen.findByText("PURCHASE-SKU")).toBeInTheDocument();
    fireEvent.click(getCatalogButton("库位/排仓数据"));
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();

    const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls).toContain("/api/input-versions/1/summary");
    expect(requestedUrls).toContain("/api/input-versions/1/preview");
    expect(requestedUrls).toContain("/api/input-versions/3/summary");
    expect(requestedUrls).toContain("/api/input-versions/3/preview");
    expect(requestedUrls.some((url) => url.includes("/2/"))).toBe(false);
    expect(requestedUrls.some((url) => url.includes("/4/"))).toBe(false);
  });

  it("does not claim content quality diagnosis for non-position inputs", async () => {
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByText("文件结构已通过校验，当前未执行内容质量诊断")).toBeInTheDocument();
    expect(screen.queryByText("未发现资料质量问题")).not.toBeInTheDocument();
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

    const purchaseButton = getCatalogButton("采购需求");
    const productButton = getCatalogButton("商品信息");
    expect(purchaseButton).toHaveAttribute("aria-pressed", "true");
    expect(purchaseButton).toHaveAccessibleName("采购需求，已就绪，当前版本 purchase-current");
    expect(productButton).toHaveAttribute("aria-pressed", "false");
    expect(productButton).toHaveAccessibleName("商品信息，未启用，等待上传");

    fireEvent.click(productButton);
    expect(purchaseButton).toHaveAttribute("aria-pressed", "false");
    expect(productButton).toHaveAttribute("aria-pressed", "true");
  });

  it("shows no-active and empty-preview states without requesting inactive versions", async () => {
    emptyPurchasePreview = true;
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
    expect(screen.getByText("supplier-old")).toBeInTheDocument();

    const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls.some((url) => url.includes("/5/"))).toBe(false);
  });

  it("uploads a replacement for the selected kind with immediate activation", async () => {
    const onVersionsChanged = vi.fn();
    const { container } = render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(getCatalogButton("库位/排仓数据"));
    await screen.findByText("SEEKWAY:US");
    fireEvent.change(screen.getByPlaceholderText("例如：position-20260721"), {
      target: { value: "position-replacement" }
    });
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: { files: [new File(["excel"], "replacement.xlsx", { type: "application/vnd.ms-excel" })] }
    });

    await waitFor(() => {
      expect(onVersionsChanged).toHaveBeenCalledOnce();
    });
    const uploadCall = vi.mocked(fetch).mock.calls.find(([input, init]) =>
      String(input).endsWith("/api/input-versions/position") && init?.method === "POST"
    );
    expect(uploadCall).toBeDefined();
    const body = uploadCall?.[1]?.body as FormData;
    expect(body.get("name")).toBe("position-replacement");
    expect(body.get("activate")).toBe("true");
    expect(body.get("file")).toBeInstanceOf(File);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("locks type switching and duplicate upload submission while an upload is pending", async () => {
    pendingUpload = createDeferred<Response>();
    const onVersionsChanged = vi.fn();
    const { container } = render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(getCatalogButton("库位/排仓数据"));
    await screen.findByText("SEEKWAY:US");
    fireEvent.change(screen.getByPlaceholderText("例如：position-20260721"), {
      target: { value: "position-slow" }
    });
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(fileInput, {
      target: { files: [new File(["first"], "first.xlsx", { type: "application/vnd.ms-excel" })] }
    });

    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.filter(([input, init]) =>
        String(input).endsWith("/api/input-versions/position") && init?.method === "POST"
      )).toHaveLength(1);
    });
    expect(getCatalogButton("商品信息")).toBeDisabled();
    const currentFileInput = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(currentFileInput).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择 Excel 并上传替换" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择 Excel 并上传替换" })).toHaveAttribute("aria-busy", "true");
    expect(within(screen.getByText("position-old").closest("tr")!).getByRole("button", { name: "启用" })).toBeDisabled();

    fireEvent.change(currentFileInput, {
      target: { files: [new File(["second"], "second.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    expect(vi.mocked(fetch).mock.calls.filter(([input, init]) =>
      String(input).endsWith("/api/input-versions/position") && init?.method === "POST"
    )).toHaveLength(1);

    pendingUpload.resolve(jsonResponse({ ...versions[2], id: 7, name: "position-slow" }, 201));
    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    expect(getCatalogButton("商品信息")).toBeEnabled();
  });

  it("downloads the current file and confirms activation of selected-type history", async () => {
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(getCatalogButton("库位/排仓数据"));
    await screen.findByText("SEEKWAY:US");
    fireEvent.click(screen.getByRole("button", { name: "下载当前文件" }));
    await waitFor(() => {
      expect(download).toHaveBeenCalledWith("/api/input-versions/3/download", "position.xlsx");
    });

    const oldVersionRow = screen.getByText("position-old").closest("tr");
    expect(oldVersionRow).not.toBeNull();
    fireEvent.click(within(oldVersionRow!).getByRole("button", { name: "启用" }));
    expect(await screen.findByText("启用 position-old？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认启用" }));

    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/input-versions/4/activate",
        expect.objectContaining({ method: "POST" })
      );
      expect(onVersionsChanged).toHaveBeenCalledOnce();
    });
  });

  it("locks type switching, upload, and other activation actions while activation is pending", async () => {
    pendingActivation = createDeferred<Response>();
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(getCatalogButton("库位/排仓数据"));
    await screen.findByText("SEEKWAY:US");
    const oldVersionRow = screen.getByText("position-old").closest("tr")!;
    const olderVersionRow = screen.getByText("position-older").closest("tr")!;
    fireEvent.click(within(oldVersionRow).getByRole("button", { name: "启用" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认启用" }));

    await waitFor(() => {
      expect(vi.mocked(fetch).mock.calls.filter(([input, init]) =>
        String(input).endsWith("/api/input-versions/4/activate") && init?.method === "POST"
      )).toHaveLength(1);
    });
    expect(getCatalogButton("商品信息")).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择 Excel 并上传替换" })).toBeDisabled();
    expect(within(oldVersionRow).getByRole("button", { name: /启用/ })).toHaveAttribute("aria-busy", "true");
    expect(within(olderVersionRow).getByRole("button", { name: "启用" })).toBeDisabled();
    fireEvent.click(within(olderVersionRow).getByRole("button", { name: "启用" }));
    expect(vi.mocked(fetch).mock.calls.filter(([input, init]) =>
      String(input).includes("/activate") && init?.method === "POST"
    )).toHaveLength(1);

    pendingActivation.resolve(jsonResponse({ ...versions[3], active: true }));
    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    expect(getCatalogButton("商品信息")).toBeEnabled();
    expect(within(olderVersionRow).getByRole("button", { name: "启用" })).toBeEnabled();
  });

  it("surfaces inspection and upload failures", async () => {
    failInspection = true;
    const onVersionsChanged = vi.fn();
    const { container } = render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByText("无法读取当前版本内容")).toBeInTheDocument();
    expect(screen.getByText("采购文件无法解析")).toBeInTheDocument();

    failUpload = true;
    fireEvent.click(getCatalogButton("库位/排仓数据"));
    await screen.findByText("SEEKWAY:US");
    fireEvent.change(screen.getByPlaceholderText("例如：position-20260721"), {
      target: { value: "broken-position" }
    });
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(fileInput!, {
      target: { files: [new File(["broken"], "broken.xlsx", { type: "application/vnd.ms-excel" })] }
    });

    expect(await screen.findByText("输入版本校验失败：缺少 MSKU_视图")).toBeInTheDocument();
    expect(onVersionsChanged).not.toHaveBeenCalled();

    fireEvent.click(getCatalogButton("供应商资料"));
    expect(screen.queryByText("输入版本校验失败：缺少 MSKU_视图")).not.toBeInTheDocument();
    fireEvent.click(getCatalogButton("库位/排仓数据"));
    expect(screen.getByText("输入版本校验失败：缺少 MSKU_视图")).toBeInTheDocument();
  });
});
