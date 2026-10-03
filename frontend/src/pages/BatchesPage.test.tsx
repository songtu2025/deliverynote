import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupBatchesPageTests, setFourteenBatches, jsonResponse } from "./batchesPageTestSupport";
import BatchesPage from "./BatchesPage";

describe("BatchesPage", () => {
  const state = setupBatchesPageTests();
  it("does not render action buttons before initial data is ready", async () => {
    const fetchMock = vi.mocked(fetch);
    let releaseLoad!: () => void;
    const loadGate = new Promise<void>((resolve) => {
      releaseLoad = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        await loadGate;
        return fetchMock(input, init);
      })
    );

    render(<BatchesPage onOpen={vi.fn()} />, { wrapper: AntApp });

    expect(screen.getByLabelText("正在加载交货批次")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /新建批次/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /同步采购数据/ })).not.toBeInTheDocument();

    releaseLoad();

    expect(await screen.findByRole("button", { name: /新建批次/ })).toBeEnabled();
    expect(await screen.findByRole("button", { name: /同步采购数据/ })).toBeEnabled();
  });
  it("shows readiness and the next batch action", async () => {
    const onOpen = vi.fn();
    const { container } = render(<BatchesPage onOpen={onOpen} />, { wrapper: AntApp });

    const status = await screen.findByRole("region", { name: "运行状态" });
    expect(within(status).getByText("基础资料")).toBeInTheDocument();
    expect(within(status).getByText("5 / 5 已就绪")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建批次/ })).toBeEnabled();
    expect(screen.getByLabelText("搜索")).toHaveAttribute("placeholder", "搜索批次名称");
    expect(screen.getByLabelText("状态")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "交货批次列表" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "积加采购数据同步" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /同步采购数据/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "统一批次流程" })).not.toBeInTheDocument();
    expect(screen.getByText("审校待处理")).toBeInTheDocument();
    expect(screen.getByText("2 个文件 · 交货 160")).toBeInTheDocument();
    expect(screen.getAllByText("短尾超收 V1").length).toBeGreaterThan(0);
    expect(container.querySelector(".ant-pagination")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("新建批次"));
    const dialog = await screen.findByRole("dialog", { name: "新建交货批次" });
    const cancel = within(dialog).getByRole("button", { name: /取\s*消/ });
    fireEvent.click(cancel);

    fireEvent.click(screen.getByRole("button", { name: "2026-07-21 交货批次" }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(7));
  });

  it("loads batch pages and applies search on the server", async () => {
    setFourteenBatches(state);
    render(<BatchesPage onOpen={vi.fn()} />, { wrapper: AntApp });

    expect(await screen.findByText("14 个批次")).toBeInTheDocument();
    const firstPage = within(screen.getByRole("table", { name: "交货批次列表" }));
    expect(firstPage.getByRole("button", { name: "交货批次 12" })).toBeInTheDocument();
    expect(firstPage.queryByText("交货批次 14", { selector: "button" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByTitle("2"));
    expect(await screen.findByRole("button", { name: "交货批次 14" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("搜索"), { target: { value: "批次 14" } });
    expect(await screen.findByText("1 个批次")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "交货批次 14" })).toBeInTheDocument();
  });
  it.each(["delivery", "self_operated_inbound"] as const)(
    "prevents creation when %s required versions are missing",
    async (workflow) => {
      const originalFetch = fetch;
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
          String(input).endsWith("/api/input-versions") ? jsonResponse([]) : originalFetch(input, init)
        )
      );
      render(<BatchesPage workflow={workflow} onOpen={vi.fn()} />, { wrapper: AntApp });
      expect(await screen.findByRole("button", { name: /新建批次/ })).toBeDisabled();
      expect(screen.getByText(/缺少：/)).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    }
  );
});
