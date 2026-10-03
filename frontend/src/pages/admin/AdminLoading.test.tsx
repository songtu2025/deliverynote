import { act, fireEvent, render as renderComponent, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import AdminPage from "../AdminPage";
import { admin, positionVersion, render, requestCount, setupAdminTests } from "./adminPageTestSupport";
import { deferred, jsonResponse } from "./positionDraftTestSupport";

describe("管理员Loading", () => {
  const state = setupAdminTests();
  it("does not render administrator content before the initial data is ready", async () => {
    const pendingVersions = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/api/input-versions") return pendingVersions.promise;
        throw new Error(`Unexpected request: GET ${url.pathname}`);
      })
    );

    render(<AdminPage currentUser={admin} />);

    expect(screen.getByLabelText("正在加载管理员维护")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "管理员维护" })).not.toBeInTheDocument();
    expect(screen.queryByText("基础资料目录")).not.toBeInTheDocument();

    await act(async () => {
      pendingVersions.resolve(jsonResponse(state.versions));
      await Promise.resolve();
    });

    expect(await screen.findByRole("heading", { name: "管理员维护" })).toBeInTheDocument();
    expect(screen.getByText("基础资料目录")).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);
  });

  it("loads administrator resources only when their tab is opened", async () => {
    render(<AdminPage currentUser={admin} />);

    expect(await screen.findByText("基础资料目录")).toBeInTheDocument();
    expect(requestCount("GET", "/api/input-versions")).toBe(1);
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "接口配置" }));
    expect(await screen.findByText("积加开放平台")).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "用户账号" }));
    expect(await screen.findByText("内部账号")).toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(1);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);

    fireEvent.click(screen.getByRole("tab", { name: "操作记录" }));
    expect(await screen.findByText("最多显示 200 条")).toBeInTheDocument();

    expect(requestCount("GET", "/api/users")).toBe(1);
    expect(requestCount("GET", "/api/input-versions")).toBe(1);
    expect(requestCount("GET", "/api/audit-logs")).toBe(1);
    expect(requestCount("GET", "/api/admin/integrations/gerpgo")).toBe(1);
    expect(requestCount("GET", "/api/purchase-sync")).toBe(0);
  });

  it("keeps only the latest StrictMode version results when earlier requests settle last", async () => {
    const staleVersions = deferred<Response>();
    const freshVersions = deferred<Response>();
    const freshPosition = { ...positionVersion, name: "position-fresh" };
    const responses = [staleVersions, freshVersions];

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname !== "/api/input-versions") {
          throw new Error(`Unexpected request: GET ${url.pathname}`);
        }
        const request = responses.shift();
        if (!request) throw new Error(`Unexpected request: GET ${url.pathname}`);
        return request.promise;
      })
    );

    renderComponent(
      <StrictMode>
        <AntApp>
          <AdminPage currentUser={admin} />
        </AntApp>
      </StrictMode>
    );
    await waitFor(() => {
      expect(requestCount("GET", "/api/input-versions")).toBe(2);
    });
    freshVersions.resolve(jsonResponse([freshPosition]));
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    staleVersions.resolve(jsonResponse([{ ...positionVersion, name: "position-stale" }]));
    await new Promise((resolve) => window.setTimeout(resolve, 0));

    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: /MSKU定位，已就绪，当前版本 position-fresh/
        })
      ).toBeInTheDocument()
    );
    expect(
      screen.queryByRole("button", {
        name: /MSKU定位，已就绪，当前版本 position-stale/
      })
    ).not.toBeInTheDocument();
    expect(requestCount("GET", "/api/users")).toBe(0);
    expect(requestCount("GET", "/api/audit-logs")).toBe(0);
  });

  it("ignores deferred administrator responses after unmount", async () => {
    const pendingVersions = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/api/input-versions") return pendingVersions.promise;
        throw new Error(`Unexpected request: GET ${url.pathname}`);
      })
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const view = render(<AdminPage currentUser={admin} />);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1));
    view.unmount();
    const errorsBeforeSettling = consoleError.mock.calls.length;

    await act(async () => {
      pendingVersions.resolve(jsonResponse([positionVersion]));
      await Promise.resolve();
    });

    expect(consoleError.mock.calls).toHaveLength(errorsBeforeSettling);
  });
});
