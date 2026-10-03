import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp, message } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupBatchesPageTests, setFourteenBatches, FocusTestApp, jsonResponse } from "./batchesPageTestSupport";
import BatchesPage from "./BatchesPage";

describe("BatchesPageDeletion", () => {
  const state = setupBatchesPageTests();
  it.each([false, true])("deletes multiple batches and reports file cleanup failure: %s", async (cleanupFailed) => {
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const response = await originalFetch(input, init);
        if (init?.method !== "DELETE" || !cleanupFailed) return response;
        return jsonResponse({ ...(await response.json()), file_cleanup_failed_ids: [7] });
      })
    );
    state.batchRows = [
      state.batchRows[0],
      {
        ...state.batchRows[0],
        id: 8,
        name: "第二个可删除批次",
        status: "failed"
      },
      {
        ...state.batchRows[0],
        id: 9,
        name: "正在计算的批次",
        status: "running"
      }
    ];
    const staticSuccess = vi.spyOn(message, "success");
    const staticWarning = vi.spyOn(message, "warning");
    render(<BatchesPage canDeleteBatches onOpen={vi.fn()} />, { wrapper: AntApp });

    await screen.findByRole("button", { name: "2026-07-21 交货批次" });
    const first = screen.getByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" });
    const second = screen.getByRole("checkbox", { name: "选择批次 第二个可删除批次" });
    const active = screen.getByRole("checkbox", { name: "选择批次 正在计算的批次" });
    expect(active).toBeDisabled();
    expect(second).toBeEnabled();
    fireEvent.click(first);
    await waitFor(() => {
      expect(document.querySelector(".batch-selection-count")).toHaveTextContent("已选 1 项");
    });
    fireEvent.click(document.querySelector('tr[data-row-key="8"] input[type="checkbox"]') as HTMLElement);
    await waitFor(() => {
      expect(document.querySelector(".batch-selection-count")).toHaveTextContent("已选 2 项");
    });
    expect(document.querySelector('tr[data-row-key="7"]')).toHaveClass("ant-table-row-selected");
    expect(document.querySelector('tr[data-row-key="8"]')).toHaveClass("ant-table-row-selected");

    fireEvent.click(screen.getByRole("button", { name: "删除已选（2）" }));
    expect(await screen.findByText("永久删除选中的 2 个批次？")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "永久删除" }));

    await waitFor(() => expect(state.deleteRequests).toEqual([[7, 8]]));
    await waitFor(() => {
      expect(screen.queryByText("2026-07-21 交货批次")).not.toBeInTheDocument();
      expect(screen.queryByText("第二个可删除批次")).not.toBeInTheDocument();
    });
    expect(screen.getByText("正在计算的批次")).toBeInTheDocument();
    expect(
      await screen.findByText(cleanupFailed ? "已删除 2 个批次，但 1 个文件目录清理失败" : "已永久删除 2 个批次")
    ).toBeInTheDocument();
    expect(staticSuccess).not.toHaveBeenCalled();
    expect(staticWarning).not.toHaveBeenCalled();
  });

  it.each(["delivery", "self_operated_inbound"] as const)(
    "restores bulk-delete focus after cancellation and Escape for %s",
    async (workflow) => {
      state.batchRows[0].workflow = workflow;
      render(<BatchesPage workflow={workflow} canDeleteBatches onOpen={vi.fn()} />, { wrapper: FocusTestApp });
      fireEvent.click(await screen.findByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" }));
      const trigger = screen.getByRole("button", { name: "删除已选（1）" });

      for (const dismiss of ["cancel", "escape"] as const) {
        trigger.focus();
        fireEvent.click(trigger);
        const popup = within(await screen.findByRole("tooltip"));
        const cancel = popup.getByRole("button", { name: /取\s*消/ });
        await waitFor(() => expect(cancel).toHaveFocus());
        if (dismiss === "cancel") fireEvent.click(cancel);
        else fireEvent.keyDown(cancel, { key: "Escape" });
        await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
        expect(trigger).toHaveFocus();
        expect(screen.getByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" })).toBeChecked();
      }

      fireEvent.click(trigger);
      const popup = within(await screen.findByRole("tooltip"));
      const confirm = popup.getByRole("button", { name: "永久删除" });
      confirm.focus();
      fireEvent.keyDown(confirm, { key: "Escape" });
      await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
      expect(trigger).toHaveFocus();
      expect(state.deleteRequests).toEqual([]);
    }
  );

  it.each(["delivery", "self_operated_inbound"] as const)(
    "does not reclaim bulk-delete focus after an outside click or leaving %s",
    async (workflow) => {
      state.batchRows[0].workflow = workflow;
      const { rerender } = render(<BatchesPage workflow={workflow} canDeleteBatches onOpen={vi.fn()} />, {
        wrapper: FocusTestApp
      });
      fireEvent.click(await screen.findByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" }));
      const trigger = screen.getByRole("button", { name: "删除已选（1）" });
      const search = screen.getByRole("textbox", { name: "搜索" });
      fireEvent.click(trigger);
      await screen.findByRole("tooltip");
      fireEvent.pointerDown(search);
      fireEvent.mouseDown(search);
      search.focus();
      fireEvent.click(search);
      await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
      expect(search).toHaveFocus();

      fireEvent.click(trigger);
      await screen.findByRole("tooltip");
      search.focus();
      rerender(<BatchesPage workflow={workflow} active={false} canDeleteBatches onOpen={vi.fn()} />);
      await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
      expect(search).toHaveFocus();
      rerender(<BatchesPage workflow={workflow} canDeleteBatches onOpen={vi.fn()} />);
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

      fireEvent.click(trigger);
      await screen.findByRole("tooltip");
      const checkbox = screen.getByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" });
      checkbox.focus();
      fireEvent.click(checkbox);
      await waitFor(() => expect(screen.queryByRole("button", { name: "删除已选（1）" })).not.toBeInTheDocument());
      expect(trigger.isConnected).toBe(false);
      expect(trigger).not.toHaveFocus();
      fireEvent.click(screen.getByRole("checkbox", { name: "选择批次 2026-07-21 交货批次" }));
      expect(screen.getByRole("button", { name: "删除已选（1）" })).toBeInTheDocument();
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
      expect(state.deleteRequests).toEqual([]);
    }
  );

  it("keeps batch selections across server pages", async () => {
    setFourteenBatches(state);
    render(<BatchesPage canDeleteBatches onOpen={vi.fn()} />, { wrapper: AntApp });

    fireEvent.click(await screen.findByRole("checkbox", { name: "选择批次 交货批次 1" }));
    fireEvent.click(screen.getByTitle("2"));
    fireEvent.click(await screen.findByRole("checkbox", { name: "选择批次 交货批次 14" }));
    expect(screen.getByText("已选 2 项")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除已选（2）" }));
    fireEvent.click(await screen.findByRole("button", { name: "永久删除" }));
    await waitFor(() => expect(state.deleteRequests).toEqual([[1, 14]]));
  });
  it("returns to the previous page when deleting the entire final page", async () => {
    setFourteenBatches(state);
    render(<BatchesPage canDeleteBatches onOpen={vi.fn()} />, { wrapper: AntApp });
    await screen.findByText("14 个批次");
    fireEvent.click(screen.getByTitle("2"));
    fireEvent.click(await screen.findByRole("checkbox", { name: "选择批次 交货批次 13" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "选择批次 交货批次 14" }));
    fireEvent.click(screen.getByRole("button", { name: "删除已选（2）" }));
    fireEvent.click(await screen.findByRole("button", { name: "永久删除" }));
    expect(await screen.findByRole("button", { name: "交货批次 1" })).toBeInTheDocument();
    expect(state.deleteRequests).toEqual([[13, 14]]);
    expect(screen.getByText("12 个批次")).toBeInTheDocument();
    expect(screen.queryByText("已选 2 项")).not.toBeInTheDocument();
  });
});
