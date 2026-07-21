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
  }
];

const jsonResponse = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "Content-Type": "application/json" }
});

let failInspection = false;
let failUpload = false;
let emptyPurchasePreview = false;

describe("InputDataPanel", () => {
  beforeEach(() => {
    failInspection = false;
    failUpload = false;
    emptyPurchasePreview = false;
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
          columns: ["SKU", "未交量"],
          rows: emptyPurchasePreview ? [] : [{ SKU: "PURCHASE-SKU", 未交量: 100 }],
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
        return jsonResponse({ ...versions[2], id: 6, name: "position-replacement" }, 201);
      }
      if (url.endsWith("/api/input-versions/4/activate") && method === "POST") {
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

    fireEvent.click(screen.getByRole("button", { name: "库位/排仓数据" }));

    expect(await screen.findByText("仅用于补充待处理导出的定位信息")).toBeInTheDocument();
    expect(await screen.findByText("1 个站点")).toBeInTheDocument();
    expect(screen.getByText("2 个警告")).toBeInTheDocument();
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();
    expect(screen.getByText("备货定位不能为空")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
    expect(onOpenPositionDraft).toHaveBeenCalledOnce();
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
    fireEvent.click(screen.getByRole("button", { name: "库位/排仓数据" }));
    expect(await screen.findByText("SEEKWAY:US")).toBeInTheDocument();

    const requestedUrls = vi.mocked(fetch).mock.calls.map(([input]) => String(input));
    expect(requestedUrls).toContain("/api/input-versions/1/summary");
    expect(requestedUrls).toContain("/api/input-versions/1/preview");
    expect(requestedUrls).toContain("/api/input-versions/3/summary");
    expect(requestedUrls).toContain("/api/input-versions/3/preview");
    expect(requestedUrls.some((url) => url.includes("/2/"))).toBe(false);
    expect(requestedUrls.some((url) => url.includes("/4/"))).toBe(false);
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
    fireEvent.click(screen.getByRole("button", { name: "供应商资料" }));
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

    fireEvent.click(screen.getByRole("button", { name: "库位/排仓数据" }));
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

    fireEvent.click(screen.getByRole("button", { name: "库位/排仓数据" }));
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
    fireEvent.click(screen.getByRole("button", { name: "库位/排仓数据" }));
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
  });
});
