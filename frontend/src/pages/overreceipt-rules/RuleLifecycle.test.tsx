import { act, renderHook, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deferred, jsonResponse } from "../admin/positionDraftTestSupport";
import { useRulesData } from "./useRulesData";

describe("超收规则请求生命周期", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse([]))
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  const mount = () =>
    renderHook(
      ({ active }) => {
        const { message } = AntApp.useApp();
        return { data: useRulesData(active), message };
      },
      { initialProps: { active: true }, wrapper: AntApp }
    );

  it("仓库选项失败后可重试，成功后复用缓存，刷新后重新读取", async () => {
    let warehouseReads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (!String(input).endsWith("/warehouses")) return jsonResponse([]);
        warehouseReads += 1;
        return warehouseReads === 1 ? jsonResponse({ detail: "仓库读取失败" }, 500) : jsonResponse(["测试仓"]);
      })
    );
    const { result } = mount();
    await waitFor(() => expect(result.current.data.loading).toBe(false));
    const error = vi.spyOn(result.current.message, "error");
    await act(() => result.current.data.loadWarehouses());
    expect(error).toHaveBeenCalledWith("仓库读取失败");
    expect(result.current.data.warehousesLoading).toBe(false);
    await act(() => result.current.data.loadWarehouses());
    expect(result.current.data.warehouses).toEqual(["测试仓"]);
    await act(() => result.current.data.loadWarehouses());
    expect(warehouseReads).toBe(2);
    act(() => result.current.data.refresh());
    await act(() => result.current.data.loadWarehouses());
    expect(warehouseReads).toBe(3);
  });

  it.each(["hidden", "unmounted"])("页面 %s 后仓库错误不再提示", async (exit) => {
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) =>
        String(input).endsWith("/warehouses") ? pending.promise : Promise.resolve(jsonResponse([]))
      )
    );
    const { result, rerender, unmount } = mount();
    await waitFor(() => expect(result.current.data.loading).toBe(false));
    const error = vi.spyOn(result.current.message, "error");
    let operation!: Promise<void>;
    act(() => {
      operation = result.current.data.loadWarehouses();
    });
    if (exit === "hidden") rerender({ active: false });
    else unmount();
    await act(async () => {
      pending.resolve(jsonResponse({ detail: "迟到的仓库错误" }, 500));
      await operation;
    });
    expect(error).not.toHaveBeenCalled();
  });

  it("刷新使旧仓库响应失效，旧响应不能重新填入清空的缓存", async () => {
    const pending = deferred<Response>();
    let warehouseReads = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (!String(input).endsWith("/warehouses")) return Promise.resolve(jsonResponse([]));
        warehouseReads += 1;
        return warehouseReads === 1 ? pending.promise : Promise.resolve(jsonResponse(["新仓库"]));
      })
    );
    const { result } = mount();
    await waitFor(() => expect(result.current.data.loading).toBe(false));
    let operation!: Promise<void>;
    act(() => {
      operation = result.current.data.loadWarehouses();
    });
    act(() => result.current.data.refresh());
    await act(() => result.current.data.loadWarehouses());
    await act(async () => {
      pending.resolve(jsonResponse(["旧仓库"]));
      await operation;
    });
    expect(result.current.data.warehouses).toEqual(["新仓库"]);
    expect(result.current.data.warehousesLoading).toBe(false);
  });

  it("离开后规则加载失败不会更新错误，返回页面也不恢复旧操作", async () => {
    const { result, rerender } = mount();
    await waitFor(() => expect(result.current.data.loading).toBe(false));
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pending.promise)
    );
    const isCurrent = result.current.data.beginOperation();
    let operation!: Promise<boolean>;
    act(() => {
      operation = result.current.data.load();
    });
    rerender({ active: false });
    await act(async () => {
      pending.resolve(jsonResponse({ detail: "迟到的规则错误" }, 500));
      await operation;
    });
    expect(result.current.data.error).toBeNull();
    expect(isCurrent()).toBe(false);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse([]))
    );
    rerender({ active: true });
    await waitFor(() => expect(result.current.data.loading).toBe(false));
    expect(isCurrent()).toBe(false);
  });
});
