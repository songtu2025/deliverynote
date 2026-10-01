import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { InputVersion } from "../../types";
import { baseDraft, basePositionVersion as version, deferred, jsonResponse } from "./positionDraftTestSupport";
import { createPositionMaintenanceTestEnvironment } from "./positionMaintenanceTestEnvironment";
import { dialogByTitle, renderMaintenance } from "./positionMaintenancePageTestSupport";

let environment: ReturnType<typeof createPositionMaintenanceTestEnvironment>;

async function startPublish() {
  const onPublished = vi.fn();
  renderMaintenance({ onPublished });
  fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
  return { onPublished, dialog: await dialogByTitle("发布新的MSKU定位版本") };
}

describe("PositionMaintenance publishing", () => {
  beforeEach(() => {
    environment = createPositionMaintenanceTestEnvironment();
    environment.install();
  });

  afterEach(() => {
    environment.dispose();
  });

  it("blocks publish when validation returns errors", async () => {
    environment.state.validationResponse = {
      ...environment.state.validationResponse,
      valid: false,
      error_count: 1,
      issues: [{ severity: "error", code: "empty_site", message: "店铺-站点不能为空", row_numbers: [2] }]
    };
    renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));

    expect(await screen.findByText("存在 1 个错误，修正后才能发布")).toBeInTheDocument();
    expect(screen.getByText("店铺-站点不能为空")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
  });

  it("requires explicit warning confirmation before publish", async () => {
    environment.state.validationResponse = {
      ...environment.state.validationResponse,
      warning_count: 1,
      issues: [{ severity: "warning", code: "custom_scale", message: "规模定位不是常用值", row_numbers: [2] }]
    };
    renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));

    expect(await screen.findByText("存在 1 个警告，请确认后发布")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "我已检查并确认发布这些警告" }));
    expect(screen.getByRole("button", { name: "确认发布" })).toBeEnabled();
  });

  it("keeps publish actions reachable when validation lists many issues", async () => {
    environment.state.validationResponse = {
      ...environment.state.validationResponse,
      warning_count: 4,
      issues: [
        { severity: "warning", code: "custom_scale", message: "规模定位必须为短尾、中尾或长尾", row_numbers: [3] },
        { severity: "warning", code: "empty_stocking", message: "备货定位不能为空", row_numbers: [3] },
        { severity: "warning", code: "row_count_changed", message: "行数变化达到或超过 50%", row_numbers: [] }
      ]
    };
    renderMaintenance();
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));

    const dialog = await dialogByTitle("发布新的MSKU定位版本");
    const body = dialog.querySelector<HTMLElement>(".ant-modal-body");
    expect(body).toHaveStyle({
      maxHeight: "calc(100vh - 300px)",
      overflowY: "auto"
    });
    const footer = dialog.querySelector<HTMLElement>(".ant-modal-footer");
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: "继续修改草稿" }));
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: "确认发布" }));
    expect(body).not.toContainElement(within(dialog).getByRole("button", { name: "确认发布" }));
  });

  it("publishes a named version and reports success to the parent", async () => {
    const onPublished = vi.fn<(published: InputVersion) => void>(() => {
      view.rerender(
        <AntApp>
          <h2>基础资料目录</h2>
        </AntApp>
      );
    });
    const view = renderMaintenance({ onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    expect(await screen.findByText("仅用于新批次；已有批次不变")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "position-20260721" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));

    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(onPublished.mock.calls[0][0]).toMatchObject({ id: 32, name: "position-20260721", active: true });
    expect(screen.queryByText("MSKU 定位维护")).not.toBeInTheDocument();
    expect(await screen.findAllByText("新库位版本已发布并启用")).toHaveLength(1);
    const body = JSON.parse(String(environment.requests("POST", "/publish")[0][1]?.body));
    expect(body).toEqual({ revision: 3, name: "position-20260721", confirm_warnings: false });
  });

  it("keeps a duplicate publish name editable and retries in the same dialog", async () => {
    environment.state.duplicatePublishNameOnce = true;
    const { onPublished, dialog } = await startPublish();
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "duplicate-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));

    expect(await within(dialog).findByText("请更换版本名称")).toBeInTheDocument();
    expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("新版本名称")).toHaveValue("duplicate-name");
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "unique-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布/ }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(environment.requests("POST", "/publish")).toHaveLength(2);
    expect(await screen.findAllByText("新库位版本已发布并启用")).toHaveLength(1);
  });

  it("refreshes metadata after a publish base-version conflict and still allows discarding", async () => {
    environment.state.publishRequestHandler = (stage) => {
      if (stage === "validate") return jsonResponse(environment.state.validationResponse);
      environment.state.draftResponse = { ...baseDraft, active_version_id: 42, active_version_name: "position-newer" };
      return jsonResponse(
        { detail: "当前启用的库位版本已变化，请放弃当前草稿后重新开始", code: "draft_base_version_changed" },
        409
      );
    };
    const { onPublished, dialog } = await startPublish();
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    await screen.findByText("草稿基线已过期");
    expect(screen.getByRole("button", { name: "放弃草稿" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /发布新版本$/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(onPublished).not.toHaveBeenCalled();
    await waitFor(() => expect(dialog).toHaveClass("ant-zoom-leave-active"));
    // jsdom 没有 AnimationEvent，动画库监听的是带前缀的结束事件。
    fireEvent(dialog, new Event("webkitAnimationEnd", { bubbles: true }));
    await waitFor(() => expect(dialog).not.toBeVisible());
  }, 30_000);

  it.each([500, 409])("preserves publish input on an ordinary failure %i and retries", async (status) => {
    let failed = false;
    environment.state.publishRequestHandler = (stage) => {
      if (stage === "validate") return jsonResponse(environment.state.validationResponse);
      if (!failed) {
        failed = true;
        return jsonResponse({ detail: "发布服务暂时不可用" }, status);
      }
      return jsonResponse({ ...version, id: 32, draft_revision: 4, draft_status: "published" }, 201);
    };
    const { onPublished, dialog } = await startPublish();
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "keep-publish-name" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    expect(await within(dialog).findByText("发布服务暂时不可用")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("新版本名称")).toHaveValue("keep-publish-name");
    expect(screen.queryByRole("button", { name: "刷新草稿" })).not.toBeInTheDocument();
    expect(onPublished).not.toHaveBeenCalled();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: /确认发布$/ })).toBeEnabled());
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布$/ }));
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(environment.requests("POST", "/publish")).toHaveLength(2);
  });

  it("clears warning confirmation on cancellation and restores the publish button focus", async () => {
    environment.state.validationResponse = { ...environment.state.validationResponse, warning_count: 1 };
    renderMaintenance();
    const trigger = await screen.findByRole("button", { name: "发布新版本" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await dialogByTitle("发布新的MSKU定位版本");
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "我已检查并确认发布这些警告" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "继续修改草稿" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(environment.requests("POST", "/publish")).toHaveLength(0);
    fireEvent.click(trigger);
    const reopened = await dialogByTitle("发布新的MSKU定位版本");
    expect(within(reopened).getByRole("checkbox", { name: "我已检查并确认发布这些警告" })).not.toBeChecked();
    expect(within(reopened).getByRole("button", { name: "确认发布" })).toBeDisabled();
  });

  it("cannot leave or cancel the publish dialog while publish is pending", async () => {
    environment.state.publishRequest = deferred<Response>();
    const onBack = vi.fn();
    const onPublished = vi.fn();
    renderMaintenance({ onBack, onPublished });
    fireEvent.click(await screen.findByRole("button", { name: "发布新版本" }));
    const dialog = await dialogByTitle("发布新的MSKU定位版本");
    fireEvent.change(within(dialog).getByLabelText("新版本名称"), { target: { value: "position-busy" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认发布" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /确认发布/ }));
    await waitFor(() => expect(environment.requests("POST", "/publish")).toHaveLength(1));

    try {
      expect(screen.getByRole("button", { name: "返回基础资料" })).toBeDisabled();
      expect(within(dialog).getByRole("button", { name: "继续修改草稿" })).toBeDisabled();
      expect(within(dialog).queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃草稿" })).toBeDisabled();
      expect(within(dialog).getByLabelText("新版本名称")).toBeDisabled();
      fireEvent.click(within(dialog).getByRole("button", { name: "继续修改草稿" }));
      fireEvent.click(screen.getByRole("button", { name: "返回基础资料" }));
      expect(onBack).not.toHaveBeenCalled();
      expect(screen.getByText("发布新的MSKU定位版本")).toBeInTheDocument();
      expect(screen.queryByText("新库位版本已发布并启用")).not.toBeInTheDocument();
    } finally {
      environment.state.publishRequest.resolve(
        jsonResponse(
          {
            ...version,
            id: 32,
            name: "position-busy",
            original_name: "position-busy.xlsx",
            draft_revision: 4,
            draft_status: "published"
          },
          201
        )
      );
    }
    await waitFor(() => expect(onPublished).toHaveBeenCalledOnce());
    expect(await screen.findAllByText("新库位版本已发布并启用")).toHaveLength(1);
  }, 30_000);
});
