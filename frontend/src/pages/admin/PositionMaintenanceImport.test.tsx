import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { baseDraft, baseImportPreview, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";
import { dialogByTitle, renderMaintenance } from "./positionMaintenancePageTestSupport";

let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;

function uploadImport(container: HTMLElement, name = "replacement.xlsx") {
  fireEvent.change(container.querySelector<HTMLInputElement>('input[type="file"]')!, {
    target: { files: [new File(["excel"], name)] }
  });
}

async function startImport(name = "replacement.xlsx") {
  const view = renderMaintenance();
  await screen.findByText("SKU-A");
  uploadImport(view.container, name);
  return { ...view, dialog: await dialogByTitle("Excel 整表替换预览") };
}

describe("PositionMaintenance Excel import", () => {
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
  });

  afterEach(() => {
    environment.dispose();
  });

  it("previews every Excel diff count before applying the server token", async () => {
    const { container } = renderMaintenance();
    await screen.findByText("SKU-A");
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    uploadImport(container);

    await waitFor(() => expect(environment.requests("POST", "/import-preview")).toHaveLength(1));
    const previewBody = environment.requests("POST", "/import-preview")[0][1]?.body as FormData;
    expect(previewBody.get("revision")).toBe("3");
    expect((previewBody.get("file") as File).name).toBe("replacement.xlsx");
    expect(environment.requests("POST", "/import-apply")).toHaveLength(0);
    expect(screen.queryByText("Excel 替换未完成")).not.toBeInTheDocument();
    const previewDialog = await dialogByTitle("Excel 整表替换预览");
    expect(within(previewDialog).getByText("新增 2")).toBeInTheDocument();
    expect(within(previewDialog).getByText("修改 1")).toBeInTheDocument();
    expect(within(previewDialog).getByText("删除 1")).toBeInTheDocument();
    expect(within(previewDialog).getByText("未变化 4")).toBeInTheDocument();
    expect(within(previewDialog).getByText("数据量变化较大")).toBeInTheDocument();
    fireEvent.click(within(previewDialog).getByRole("button", { name: "应用整表替换" }));

    await waitFor(() => expect(environment.requests("POST", "/import-apply")).toHaveLength(1));
    expect(JSON.parse(String(environment.requests("POST", "/import-apply")[0][1]?.body))).toEqual({
      revision: 3,
      token: "preview-token"
    });
    expect(await screen.findByText("修订号 6")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^复制 / }));
    await waitFor(() => expect(environment.requests("POST", "/api/input-drafts/7/rows")).toHaveLength(1));
    expect(JSON.parse(String(environment.requests("POST", "/api/input-drafts/7/rows")[0][1]?.body)).revision).toBe(6);
  });

  it("recovers from an expired import token without applying the candidate", async () => {
    environment.state.expireImportApply = true;
    const { container, dialog } = await startImport("expired.xlsx");
    await waitFor(() => expect(environment.requests("POST", "/import-preview")).toHaveLength(1));
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));

    expect(await screen.findByText("请重新上传表格预览")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();

    uploadImport(container, "retry.xlsx");
    await waitFor(() => expect(environment.requests("POST", "/import-preview")).toHaveLength(2));
  });

  it("cancels import without writing and opens only the next file preview", async () => {
    const { container, dialog } = await startImport("cancelled.xlsx");
    fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "Excel 整表替换" })).toHaveFocus());
    expect(environment.requests("POST", "/import-apply")).toHaveLength(0);
    uploadImport(container, "next.xlsx");
    expect(await screen.findByText("即将用 next.xlsx 的 2 行完整替换当前草稿")).toBeInTheDocument();
    expect(screen.queryByText(/即将用 cancelled.xlsx/)).not.toBeInTheDocument();
    expect(screen.getByText("修订号 3")).toBeInTheDocument();
  });

  it("keeps failed apply local and requires reupload if its token was consumed", async () => {
    let failed = false;
    environment.state.importRequestHandler = (stage) => {
      if (stage === "preview") return jsonResponse(baseImportPreview);
      if (!failed) {
        failed = true;
        return jsonResponse({ detail: "替换暂时失败" }, 500);
      }
      return jsonResponse({ detail: "令牌已消费，请重新预览", code: "draft_import_preview_expired" }, 409);
    };
    const { dialog } = await startImport();
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
    expect(await screen.findByText("替换暂时失败")).toBeInTheDocument();
    expect(screen.getByText("修订号 3")).toBeInTheDocument();
    expect(screen.queryByText("Excel 已完整替换服务器草稿")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    const retry = within(dialog).getByRole("button", { name: /应用整表替换/ });
    await waitFor(() => expect(retry).not.toHaveClass("ant-btn-loading"));
    fireEvent.click(retry);
    expect(await screen.findByText("令牌已消费，请重新预览")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument());
    expect(environment.requests("POST", "/import-apply")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();
  });

  it.each(["preview", "apply"] as const)(
    "locks the workspace for %s revision conflict and refreshes it",
    async (stage) => {
      environment.state.importRequestHandler = (currentStage) =>
        currentStage === stage
          ? jsonResponse({ detail: "导入修订号冲突", code: "draft_revision_conflict" }, 409)
          : jsonResponse(baseImportPreview);
      const { container } = renderMaintenance();
      await screen.findByText("SKU-A");
      uploadImport(container);
      if (stage === "apply") {
        const dialog = await dialogByTitle("Excel 整表替换预览");
        fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
      }
      expect(await screen.findByText("导入修订号冲突")).toBeInTheDocument();
      expect(screen.queryByText("Excel 替换未完成")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeDisabled();
      expect(screen.queryByRole("dialog", { name: "Excel 整表替换预览" })).not.toBeInTheDocument();
      environment.state.draftResponse = { ...baseDraft, revision: 9 };
      fireEvent.click(screen.getByRole("button", { name: "刷新草稿" }));
      expect(await screen.findByText("修订号 9")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Excel 整表替换" })).toBeEnabled();
    }
  );

  it("cannot leave or cancel the import dialog while apply is pending", async () => {
    environment.state.importApplyRequest = deferred<Response>();
    const { dialog } = await startImport();
    fireEvent.click(within(dialog).getByRole("button", { name: "应用整表替换" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /应用整表替换/ }));
    await waitFor(() => expect(environment.requests("POST", "/import-apply")).toHaveLength(1));

    try {
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: /取\s*消/ })).toBeDisabled();
      expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃草稿" })).toBeDisabled();
      fireEvent.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
      expect(screen.getByText("Excel 整表替换预览")).toBeInTheDocument();
      expect(screen.queryByText("Excel 已完整替换服务器草稿")).not.toBeInTheDocument();
    } finally {
      environment.state.importApplyRequest.resolve(jsonResponse({ diff: baseImportPreview.diff, revision: 6 }));
    }
    expect(await screen.findByText("修订号 6")).toBeInTheDocument();
    expect(await screen.findAllByText("Excel 已完整替换服务器草稿")).toHaveLength(1);
  });
});
