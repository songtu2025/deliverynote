import { fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { api, AUTH_EXPIRED_EVENT } from "../api";
import { jsonResponse } from "./admin/positionDraftTestSupport";
import { fixtureJob } from "./batch-detail/detailFixtures";
import { describe } from "vitest";
import BatchDetail from "./BatchDetail";
import { renderDetail, setupBatchDetailTest } from "./batchDetailTestSupport";

describe("BatchDetail", () => {
  const { state, exceptionPage, exceptionFilters } = setupBatchDetailTest();

  it.each(["server", "network"])("recovers an initial %s failure with read-only retry", async (failure) => {
    const originalFetch = fetch;
    let failing = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/api/batches/7") && failing) {
          if (failure === "network") throw new Error("网络连接失败");
          return new Response(JSON.stringify({ detail: "服务暂不可用 <&>" }), { status: 500 });
        }
        return originalFetch(input, init);
      })
    );
    const onBack = vi.fn();
    renderDetail(<BatchDetail batchId={7} onBack={onBack} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      failure === "network" ? "网络连接失败" : "服务暂不可用 <&>"
    );
    fireEvent.click(screen.getByRole("button", { name: /返回批次列表/ }));
    expect(onBack).toHaveBeenCalledOnce();
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: /重试/ }));
    await screen.findByText("160 = 100 + 60");
    expect(screen.queryByText("读取批次失败")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  });

  it("leaves concurrent initial unauthorized feedback to session handling", async () => {
    await api("/api/auth/me");
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response(JSON.stringify({ detail: "未登录" }), { status: 401 }))
      );
      renderDetail(<BatchDetail batchId={7} canRefreshSupplierVersion onBack={vi.fn()} />);
      await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
      await waitFor(() => expect(expired).toHaveBeenCalledOnce());
      expect(screen.queryByText("未登录")).not.toBeInTheDocument();
      expect(screen.queryByText("读取批次失败")).not.toBeInTheDocument();
      expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
    } finally {
      window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    }
  });

  it.each([403, 409, 422, 500])("shows a %s operation failure and releases its loading state", async (status) => {
    state.batch.status = "draft";
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/preflight"))
          return new Response(JSON.stringify({ detail: `预检失败 ${status}` }), { status });
        return originalFetch(input, init);
      })
    );
    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
    const button = await screen.findByRole("button", { name: /执行预检/ });
    fireEvent.click(button);
    await screen.findByText(`预检失败 ${status}`);
    expect(button).not.toHaveClass("ant-btn-loading");
    expect(screen.queryByText("所有基础资料和交货文件均已通过预检")).not.toBeInTheDocument();
  });

  it.each(["operation", "refresh", "download", "poll", "poll-refresh"])(
    "suppresses page feedback for unauthorized %s",
    async (phase) => {
      await api("/api/auth/me");
      state.batch.status = "draft";
      if (phase === "download") {
        state.batch.status = "succeeded";
        state.batch.file_count = 1;
        state.batch.files = [state.batch.files[0]];
        state.batch.files[0].download_ready = true;
        state.batch.download_ready = true;
      }
      if (phase.startsWith("poll")) state.batch.jobs = { compute: fixtureJob() };
      const originalFetch = fetch;
      let refreshing = false;
      const unauthorized = () => new Response(JSON.stringify({ detail: "未登录" }), { status: 401 });
      const expired = vi.fn();
      window.addEventListener(AUTH_EXPIRED_EVENT, expired);
      try {
        vi.stubGlobal(
          "fetch",
          vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            if (url.endsWith("/preflight")) {
              refreshing = true;
              return phase === "operation" ? unauthorized() : jsonResponse(state.batch);
            }
            if (url.endsWith("/api/jobs/88")) {
              refreshing = true;
              return phase === "poll" ? unauthorized() : jsonResponse({ id: 88, kind: "compute", status: "succeeded" });
            }
            if (url.endsWith("/download")) return unauthorized();
            if (refreshing && url.endsWith("/api/batches/7")) return unauthorized();
            return originalFetch(input, init);
          })
        );
        renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);
        await screen.findByText(state.batch.name);
        if (phase === "operation" || phase === "refresh")
          fireEvent.click(screen.getByRole("button", { name: /执行预检/ }));
        if (phase === "download") fireEvent.click(screen.getAllByRole("button", { name: /下载处理结果/ })[0]);
        await waitFor(() => expect(expired).toHaveBeenCalledOnce());
        await waitFor(() => expect(document.querySelector(".ant-btn-loading")).not.toBeInTheDocument());
        expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
      } finally {
        window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
      }
    }
  );

  it("shows the batch overview before exception enrichment finishes", async () => {
    let finishExceptions: (response: Response) => void = () => undefined;
    const delayedExceptions = new Promise<Response>((resolve) => {
      finishExceptions = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/batches/7/exceptions?")) return delayedExceptions;
        if (url.endsWith("/api/batches/7/exceptions/filters")) return Promise.resolve(jsonResponse(exceptionFilters()));
        if (url.endsWith("/api/batches/7")) {
          return Promise.resolve(jsonResponse(state.batch));
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByText("160 = 100 + 60")).toBeInTheDocument();
    expect(screen.queryByText("SKU-A")).not.toBeInTheDocument();

    finishExceptions(
      jsonResponse(exceptionPage("/api/batches/7/exceptions?offset=0&limit=10&review_scope=unfinished"))
    );
    expect(await screen.findByText("SKU-A")).toBeInTheDocument();
  });

  it("shows exception loading during a silent job refresh", async () => {
    let finishRefresh: (response: Response) => void = () => undefined;
    const delayedRefresh = new Promise<Response>((resolve) => {
      finishRefresh = resolve;
    });
    let exceptionRequests = 0;
    state.batch.jobs = {
      compute: fixtureJob()
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/jobs/88")) {
          return Promise.resolve(
            jsonResponse({
              id: 88,
              kind: "compute",
              status: "succeeded"
            })
          );
        }
        if (url.includes("/api/batches/7/exceptions?")) {
          exceptionRequests += 1;
          return exceptionRequests === 1 ? Promise.resolve(jsonResponse(exceptionPage(url))) : delayedRefresh;
        }
        if (url.endsWith("/api/batches/7/exceptions/filters")) return Promise.resolve(jsonResponse(exceptionFilters()));
        if (url.endsWith("/api/batches/7")) {
          return Promise.resolve(jsonResponse(state.batch));
        }
        throw new Error(`Unexpected request: ${url}`);
      })
    );

    const { container } = renderDetail(<BatchDetail batchId={7} onBack={vi.fn()} />);

    expect(await screen.findByText("160 = 100 + 60")).toBeInTheDocument();
    await waitFor(() => expect(exceptionRequests).toBe(2));
    await waitFor(() => {
      expect(container.querySelector(".exception-review-card.ant-card-loading")).toBeInTheDocument();
    });

    finishRefresh(jsonResponse(exceptionPage("/api/batches/7/exceptions?offset=0&limit=10&review_scope=unfinished")));
    await waitFor(() => {
      expect(container.querySelector(".exception-review-card.ant-card-loading")).not.toBeInTheDocument();
    });
  });
});
