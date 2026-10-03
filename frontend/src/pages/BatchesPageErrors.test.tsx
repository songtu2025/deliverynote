import { act, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp, message } from "antd";
import { describe, expect, it, vi } from "vitest";
import { setupBatchesPageTests, rejectBatchRequest, submitBatchAction } from "./batchesPageTestSupport";
import BatchesPage from "./BatchesPage";

describe("BatchesPageErrors", () => {
  const state = setupBatchesPageTests();
  it.each(["delivery", "self_operated_inbound"] as const)(
    "leaves unauthorized %s list errors to the shared authentication handler",
    async (workflow) => {
      const errorMessage = vi.spyOn(message, "error");
      rejectBatchRequest(401, "未登录");
      render(<BatchesPage workflow={workflow} onOpen={vi.fn()} />, { wrapper: AntApp });

      await waitFor(() => expect(screen.getByRole("button", { name: /新建批次/ })).toBeInTheDocument());
      expect(errorMessage).not.toHaveBeenCalled();
      expect(screen.queryByText("未登录")).not.toBeInTheDocument();
    }
  );

  it.each([403, 500])("still displays batch list errors with status %i", async (status) => {
    const errorMessage = vi.spyOn(message, "error");
    rejectBatchRequest(status, "批次读取测试错误");
    render(<BatchesPage onOpen={vi.fn()} />, { wrapper: AntApp });

    expect(await screen.findByText("批次读取测试错误")).toBeInTheDocument();
    expect(errorMessage).not.toHaveBeenCalled();
  });

  it.each(["create", "delete", "clean"] as const)("does not repeat unauthorized %s feedback", async (action) => {
    state.batchRows[0] = { ...state.batchRows[0], status: "draft", file_count: 0 };
    const errorMessage = vi.spyOn(message, "error");
    rejectBatchRequest(401, "未登录", action === "create" ? "POST" : "DELETE");
    render(<BatchesPage canDeleteBatches onOpen={vi.fn()} />, { wrapper: AntApp });
    await submitBatchAction(action);

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ method: action === "create" ? "POST" : "DELETE" })
      )
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.queryByText("未登录")).not.toBeInTheDocument();
    expect(errorMessage).not.toHaveBeenCalled();
  });

  it.each([403, 422, 500, 0])("keeps failed mutations visible for status %i", async (status) => {
    const errorMessage = vi.spyOn(message, "error");
    rejectBatchRequest(status, "合成操作错误", "DELETE");
    render(<BatchesPage canDeleteBatches onOpen={vi.fn()} />, { wrapper: AntApp });
    await submitBatchAction("delete");

    expect(await screen.findByText("合成操作错误")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2026-07-21 交货批次" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "删除已选（1）" })).not.toHaveClass("ant-btn-loading")
    );
    expect(errorMessage).not.toHaveBeenCalled();
  });
});
