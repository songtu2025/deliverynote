import { fireEvent, render as renderComponent, screen, within } from "@testing-library/react";
import { App as AntApp, ConfigProvider, message as staticMessage } from "antd";
import type { ReactElement } from "react";
import { afterEach, beforeEach, vi } from "vitest";

import { download } from "../../api";
import type { InputVersion } from "../../types";
import { jsonResponse } from "./positionDraftTestSupport";
import type { Deferred } from "./positionDraftTestSupport";

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, download: vi.fn() };
});

export const versions: InputVersion[] = [
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

export function render(ui: ReactElement) {
  return renderComponent(ui, {
    wrapper: ({ children }) => (
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp message={{ top: 64 }}>{children}</AntApp>
      </ConfigProvider>
    )
  });
}

export const getCatalogButton = (label: string) =>
  screen.getByRole("button", {
    name: new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`)
  });

export async function confirmHistoryActivation() {
  fireEvent.click(screen.getByText(/版本记录/, { selector: ".ant-tabs-tab-btn > span" }));
  fireEvent.click(
    within(screen.getByText("product-old").closest("tr")!).getByText("启用", { selector: "button > span" })
  );
  fireEvent.click(await screen.findByText("确认启用", { selector: "button > span" }));
}

export function setupInputDataPanelTests() {
  const state = {
    failInspection: false,
    failUpload: false,
    failActivation: false,
    emptyProductPreview: false,
    pendingUpload: null as Deferred<Response> | null,
    pendingActivation: null as Deferred<Response> | null
  };
  beforeEach(() => {
    state.failInspection = false;
    state.failUpload = false;
    state.failActivation = false;
    state.emptyProductPreview = false;
    state.pendingUpload = null;
    state.pendingActivation = null;
    vi.mocked(download).mockReset();
    vi.spyOn(staticMessage, "success");
    vi.spyOn(staticMessage, "error");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";

        if (url.endsWith("/api/input-versions/7/inspection")) {
          if (state.failInspection) return jsonResponse({ detail: "商品文件无法解析" }, 400);
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
              rows: state.emptyProductPreview
                ? []
                : [{ SKU: "PRODUCT-SKU", "店铺/站点": "SEEKWAY:US", 已锁定: true, 需复核: false }],
              total: state.emptyProductPreview ? 0 : 1,
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
          if (state.failUpload) return jsonResponse({ detail: "输入版本校验失败：缺少 SKU" }, 400);
          if (state.pendingUpload) return state.pendingUpload.promise;
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
          if (state.failActivation) return jsonResponse({ detail: "合成版本启用失败" }, 400);
          if (state.pendingActivation) return state.pendingActivation.promise;
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

  return state;
}
