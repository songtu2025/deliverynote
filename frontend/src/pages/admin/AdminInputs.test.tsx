import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as apiModule from "../../api";
import AdminPage from "../AdminPage";
import { admin, positionVersion, render, requestCount, setupAdminTests } from "./adminPageTestSupport";
import { deferred, jsonResponse } from "./positionDraftTestSupport";

describe("管理员Inputs", () => {
  const state = setupAdminTests();
  it("opens position maintenance in place and returns focus to the input catalog", async () => {
    state.versions = [positionVersion];
    state.positionFlow = true;
    render(<AdminPage currentUser={admin} />);

    await screen.findByText("基础资料目录");
    fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
    const maintenanceEntry = screen.getByRole("button", { name: "开始网页维护" });
    fireEvent.click(maintenanceEntry);
    expect(await screen.findByText("MSKU 定位维护")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "返回基础资料" })).toHaveFocus());

    fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
    await waitFor(() => expect(screen.queryByText("MSKU 定位维护")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "基础资料目录" })).toHaveFocus();
  }, 30_000);

  it("returns from position entry loading and restores focus to the input catalog", async () => {
    state.versions = [positionVersion];
    state.positionFlow = true;
    state.positionEntryRequest = deferred<Response>();
    const view = render(<AdminPage currentUser={admin} />);

    try {
      await screen.findByText("基础资料目录");
      fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
      fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
      expect(await screen.findByText("正在创建或恢复服务器草稿")).toBeInTheDocument();
      await waitFor(() => expect(screen.getByRole("button", { name: "返回基础资料" })).toHaveFocus());

      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      await waitFor(() => expect(screen.getByRole("heading", { name: "基础资料目录" })).toHaveFocus());
    } finally {
      view.unmount();
      state.positionEntryRequest?.resolve(jsonResponse({}));
    }
  });

  it.each([200, 401, 500, "network"])(
    "separates position publication from catalog refresh (%s)",
    async (status) => {
      state.versions = [positionVersion];
      state.positionFlow = true;
      await apiModule.api("/api/auth/me");
      const authExpired = vi.fn();
      window.addEventListener(apiModule.AUTH_EXPIRED_EVENT, authExpired, { once: true });
      const refresh = deferred<Response>();
      const originalFetch = vi.mocked(fetch).getMockImplementation()!;
      let refreshHandled = false;
      vi.mocked(fetch).mockImplementation((input, init) => {
        if (
          String(input).endsWith("/api/input-versions") &&
          requestCount("GET", "/api/input-versions") === 2 &&
          !refreshHandled
        ) {
          refreshHandled = true;
          return refresh.promise.then((response) => {
            if (status === "network") throw new TypeError("Failed to fetch");
            return response;
          });
        }
        return originalFetch(input, init);
      });
      render(<AdminPage currentUser={admin} />);

      await screen.findByText("基础资料目录");
      fireEvent.click(screen.getByRole("button", { name: /^MSKU定位/ }));
      fireEvent.click(screen.getByRole("button", { name: "开始网页维护" }));
      fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
      fireEvent.change(await screen.findByLabelText("新版本名称"), { target: { value: "position-published" } });
      fireEvent.click(screen.getByRole("button", { name: "确认发布" }));

      await waitFor(() => expect(requestCount("GET", "/api/input-versions")).toBe(2));
      expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
      await act(async () =>
        refresh.resolve(
          jsonResponse(
            status === 200 ? state.versions : { detail: "目录读取失败" },
            typeof status === "number" ? status : 500
          )
        )
      );
      if (status === 401) {
        expect(authExpired).toHaveBeenCalledOnce();
        expect(screen.queryByText("目录读取失败")).not.toBeInTheDocument();
        expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
      } else {
        await waitFor(() => expect(screen.queryByText("MSKU 定位维护")).not.toBeInTheDocument());
        if (status !== 200) {
          expect(screen.getByText(/库位版本已发布，但读取基础资料目录失败/)).toBeInTheDocument();
          expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
          fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
        }
        await screen.findByRole("button", { name: /MSKU定位，已就绪，当前版本 position-published/ });
        await waitFor(() => expect(screen.getByRole("heading", { name: "基础资料目录" })).toHaveFocus());
      }
      window.removeEventListener(apiModule.AUTH_EXPIRED_EVENT, authExpired);
      expect(requestCount("POST", "/api/input-drafts/7/publish")).toBe(1);
      expect(requestCount("GET", "/api/users")).toBe(0);
      expect(requestCount("GET", "/api/audit-logs")).toBe(0);
    },
    30_000
  );

  it.each([500, 401])("distinguishes saved input activation from a failed refresh (%s)", async (status) => {
    state.versions = [{ ...positionVersion, kind: "product", active: false }];
    await apiModule.api("/api/auth/me");
    const originalFetch = vi.mocked(fetch).getMockImplementation()!;
    let saved = false;
    let failRefresh = true;
    vi.mocked(fetch).mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/input-versions/31/activate")) {
        saved = true;
        state.versions = state.versions.map((version) => ({ ...version, active: true }));
        return Promise.resolve(jsonResponse(state.versions[0]));
      }
      if (url.endsWith("/api/input-versions") && saved && failRefresh) {
        return Promise.resolve(jsonResponse({ detail: "合成刷新失败" }, status));
      }
      return originalFetch(input, init);
    });
    render(<AdminPage currentUser={admin} />);
    await screen.findByText("商品信息尚无启用版本");
    fireEvent.click(screen.getByText(/版本记录/, { selector: ".ant-tabs-tab-btn > span" }));
    fireEvent.click(
      within(screen.getByText("position-current").closest("tr")!).getByText("启用", { selector: "button > span" })
    );
    fireEvent.click(await screen.findByText("确认启用", { selector: "button > span" }));
    if (status === 500) {
      await screen.findByText("变更已保存，但读取基础资料失败：合成刷新失败");
      failRefresh = false;
      fireEvent.click(screen.getByText("重新加载", { selector: "button > span" }));
      await waitFor(() => expect(screen.queryByText("无法读取基础资料")).not.toBeInTheDocument());
      expect(requestCount("GET", "/api/input-versions")).toBe(3);
    } else {
      await waitFor(() => expect(requestCount("GET", "/api/input-versions")).toBe(2));
      await waitFor(() =>
        expect(screen.getByText("上传首个版本", { selector: "button > span" }).closest("button")).toBeEnabled()
      );
      expect(screen.queryByText("合成刷新失败")).not.toBeInTheDocument();
    }
    expect(screen.queryByText("position-current 已启用，将用于新批次")).not.toBeInTheDocument();
    expect(requestCount("POST", "/api/input-versions/31/activate")).toBe(1);
  });
});
