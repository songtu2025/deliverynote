import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PositionMaintenance } from "./PositionMaintenance";
import { baseDraft, basePositionVersion, baseRow, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";
import { dialogByTitle, renderMaintenance } from "./positionMaintenancePageTestSupport";

describe("库位维护加载与当前操作", () => {
  let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
  });
  afterEach(() => environment.dispose());

  it("does not reopen the draft when parent callbacks and catalog version change", async () => {
    const view = renderMaintenance();
    await screen.findByText("SKU-A");
    view.rerender(
      <AntApp>
        <PositionMaintenance
          activeVersion={{ ...basePositionVersion, id: 99 }}
          onPublished={vi.fn()}
          onBack={vi.fn()}
        />
      </AntApp>
    );
    fireEvent.change(screen.getByLabelText("搜索草稿"), { target: { value: "SKU-A" } });
    expect(environment.requests("POST", "/api/input-drafts/position")).toHaveLength(1);
    expect(screen.getByText(new RegExp(`基于 ${baseDraft.base_version_name}`))).toBeInTheDocument();
  });

  it.each(["复制", "编辑", "删除"])(
    "uses the refreshed draft and revision for %s after a late resume",
    async (action) => {
      renderMaintenance();
      await screen.findByText("SKU-A");
      const resumed = deferred<Response>();
      environment.state.entryRequest = resumed;
      environment.state.publishRequestHandler = (stage) =>
        stage === "validate"
          ? jsonResponse(environment.state.validationResponse)
          : jsonResponse({ detail: "正式版本已改变，请重新读取草稿", code: "draft_base_version_changed" }, 409);
      fireEvent.click(screen.getByRole("button", { name: "发布新版本" }));
      const dialog = await dialogByTitle("发布新的MSKU定位版本");
      fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
      expect(await screen.findByText("正式版本已改变，请重新读取草稿")).toBeInTheDocument();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" })).toBeEnabled()
      );

      const nextDraft = { ...baseDraft, id: 17, revision: 21 };
      const nextRow = { ...baseRow, draft_id: nextDraft.id };
      const originalFetch = environment.fetch.getMockImplementation()!;
      environment.fetch.mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/api/input-drafts/17/rows")) {
          if ((init?.method ?? "GET") === "GET") {
            return jsonResponse({ rows: [nextRow], total: 1, offset: 0, limit: 20 });
          }
          environment.state.metadataResponse = { ...nextDraft, revision: 22 };
          return init?.method === "DELETE"
            ? jsonResponse({ row_id: nextRow.id, revision: 22 })
            : jsonResponse({ row: nextRow, revision: 22 }, 201);
        }
        return originalFetch(input, init);
      });
      await act(async () => resumed.resolve(jsonResponse(nextDraft)));
      expect(await screen.findByText("修订号 21")).toBeInTheDocument();
      await waitFor(() => expect(environment.requests("GET", "/api/input-drafts/17/rows")).toHaveLength(1));
      fireEvent.click(screen.getByRole("button", { name: `${action} SEEKWAY:US / SKU-A / MSKU-A` }));
      if (action === "编辑") {
        const editor = await dialogByTitle("编辑库位记录：SKU-A");
        fireEvent.click(within(editor).getByRole("button", { name: "保存到草稿" }));
      } else if (action === "删除") {
        fireEvent.click(await screen.findByRole("button", { name: "确认删除" }));
      }
      const method = action === "复制" ? "POST" : action === "编辑" ? "PUT" : "DELETE";
      await waitFor(() => expect(environment.requests(method, "/api/input-drafts/17/rows")).toHaveLength(1));
      const [, request] = environment.requests(method, "/api/input-drafts/17/rows")[0];
      expect(JSON.parse(String(request?.body)).revision).toBe(21);
      expect(await screen.findByText("修订号 22")).toBeInTheDocument();
    },
    30_000
  );

  it("clears selection and the conflict when manually reopening the server draft", async () => {
    environment.state.conflictNextRowWrite = true;
    renderMaintenance();
    await screen.findByText("SKU-A");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 1" }));
    fireEvent.click(screen.getByRole("button", { name: "复制 SEEKWAY:US / SKU-A / MSKU-A" }));
    expect(await screen.findByText("草稿已在其他位置更新")).toBeInTheDocument();
    environment.state.draftResponse = { ...baseDraft, revision: 11 };
    fireEvent.click(screen.getByRole("button", { name: "刷新草稿" }));
    expect(await screen.findByText("修订号 11")).toBeInTheDocument();
    expect(screen.queryByText("草稿已在其他位置更新")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select row 1" })).not.toBeChecked();
    expect(environment.requests("POST", "/api/input-drafts/position")).toHaveLength(2);
  });
});
