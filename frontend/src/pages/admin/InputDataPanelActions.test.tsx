import {
  render,
  setupInputDataPanelTests,
  versions,
  getCatalogButton,
  confirmHistoryActivation
} from "./inputDataPanelTestSupport";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { message as staticMessage } from "antd";
import { describe, expect, it, vi } from "vitest";

import { download } from "../../api";
import { jsonResponse, deferred as createDeferred } from "./positionDraftTestSupport";
import { InputDataPanel } from "./InputDataPanel";

const state = setupInputDataPanelTests();

describe("InputDataPanel 版本操作", () => {
  it.each(["success", "failure", "pending"])(
    "preserves history activation feedback and locking with outcome=%s",
    async (outcome) => {
      const failed = outcome === "failure";
      state.failActivation = failed;
      const response = outcome === "pending" ? createDeferred<Response>() : null;
      state.pendingActivation = response;
      const onVersionsChanged = vi.fn();
      render(
        <InputDataPanel
          versions={versions}
          loading={false}
          onVersionsChanged={onVersionsChanged}
          onOpenPositionDraft={vi.fn()}
        />
      );
      fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
      const historyRow = screen.getByText("product-old").closest("tr")!;
      const activateButton = within(historyRow).getByRole("button", { name: "启用" });
      fireEvent.click(activateButton);
      expect(onVersionsChanged).not.toHaveBeenCalled();
      fireEvent.click(await screen.findByRole("button", { name: "确认启用" }));

      if (response) {
        await waitFor(() => expect(activateButton).toBeDisabled());
        expect(activateButton).toHaveAttribute("aria-busy", "true");
        expect(getCatalogButton("供应商资料")).toBeDisabled();
        expect(onVersionsChanged).not.toHaveBeenCalled();
        fireEvent.click(activateButton);
        expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
        response.resolve(jsonResponse({ ...versions[7], active: true }));
      }

      const successText = "product-old 已启用，将用于新批次";
      if (failed) {
        expect(await screen.findByText("合成版本启用失败")).toBeInTheDocument();
        expect(onVersionsChanged).not.toHaveBeenCalled();
        expect(screen.queryByText(successText)).not.toBeInTheDocument();
        expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
      } else {
        const feedback = await screen.findByText(successText);
        expect(onVersionsChanged).toHaveBeenCalledOnce();
        expect(screen.getAllByText(successText)).toHaveLength(1);
        expect(feedback.closest<HTMLElement>(".ant-message")?.style.getPropertyValue("--notification-top")).toBe(
          "64px"
        );
      }
      expect(staticMessage.success).not.toHaveBeenCalled();
      expect(staticMessage.error).not.toHaveBeenCalled();
      expect(
        vi
          .mocked(fetch)
          .mock.calls.filter(
            ([input, init]) => String(input).endsWith("/api/input-versions/8/activate") && init?.method === "POST"
          )
      ).toHaveLength(1);
      await waitFor(() => expect(activateButton).toBeEnabled());
      expect(getCatalogButton("供应商资料")).toBeEnabled();
    },
    30_000
  );
  it("locks type switching and duplicate upload submission while an upload is pending", async () => {
    state.pendingUpload = createDeferred<Response>();
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    await screen.findByText("PRODUCT-SKU");
    fireEvent.click(screen.getByRole("tab", { name: /版本记录/ }));
    const supplierButton = getCatalogButton("供应商资料");
    // 单独检查可见性和隐藏祖先，避免角色查询重复计算深层表格按钮的样式。
    const historyActivateButton = within(screen.getByText("product-old").closest("tr")!).getByRole("button", {
      name: "启用",
      hidden: true
    });
    expect(historyActivateButton).toBeVisible();
    expect(historyActivateButton.closest('[hidden], [aria-hidden="true"]')).toBeNull();
    const status = within(screen.getByRole("region", { name: "商品信息资料状态" }));
    const updateButton = status.getByRole("button", { name: "更新资料" });
    fireEvent.click(updateButton);
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "product-slow" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(fileInput, {
      target: { files: [new File(["first"], "first.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("first.xlsx");
    const submitButton = screen.getByRole("button", { name: "校验并启用新版本" });
    try {
      submitButton.click();
      await waitFor(() => {
        expect(
          vi
            .mocked(fetch)
            .mock.calls.filter(
              ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
            )
        ).toHaveLength(1);
      });
      expect(supplierButton).toBeDisabled();
      const currentFileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
      expect(currentFileInput).toBeDisabled();
      expect(submitButton).toBeDisabled();
      expect(submitButton).toHaveAttribute("aria-busy", "true");
      expect(historyActivateButton).toBeDisabled();

      fireEvent.change(currentFileInput, {
        target: { files: [new File(["second"], "second.xlsx", { type: "application/vnd.ms-excel" })] }
      });
      expect(
        vi
          .mocked(fetch)
          .mock.calls.filter(
            ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
          )
      ).toHaveLength(1);
    } finally {
      state.pendingUpload?.resolve(jsonResponse({ ...versions[6], id: 9, name: "product-slow" }, 201));
    }

    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    expect(supplierButton).toBeEnabled();
  }, 30_000);
  it("downloads the current file from the selected-type status header", async () => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );

    fireEvent.click(screen.getByRole("button", { name: "下载当前文件" }));
    await waitFor(() => {
      expect(download).toHaveBeenCalledWith("/api/input-versions/7/download", "product.xlsx");
    });
  });
  it.each(["upload", "activate"])(
    "does not report %s success when the saved list cannot refresh",
    async (operation) => {
      const onVersionsChanged = vi.fn().mockResolvedValue(false);
      render(
        <InputDataPanel
          versions={versions}
          loading={false}
          onVersionsChanged={onVersionsChanged}
          onOpenPositionDraft={vi.fn()}
        />
      );
      await screen.findByText("PRODUCT-SKU");
      if (operation === "upload") {
        fireEvent.click(screen.getByText("更新资料", { selector: "button > span" }));
        fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "saved-version" } });
        fireEvent.change(document.querySelector('input[type="file"]')!, {
          target: { files: [new File(["synthetic"], "saved.xlsx")] }
        });
        await screen.findByText("saved.xlsx");
        fireEvent.click(screen.getByText("校验并启用新版本", { selector: "button > span" }));
      } else {
        await confirmHistoryActivation();
      }
      await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
      await waitFor(() => expect(getCatalogButton("供应商资料")).toBeEnabled());
      expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
      expect(screen.queryByText("上传失败")).not.toBeInTheDocument();
      if (operation === "upload") {
        expect(screen.queryByLabelText("新版本名称")).not.toBeInTheDocument();
        fireEvent.click(screen.getByText("更新资料", { selector: "button > span" }));
        expect(screen.getByLabelText("新版本名称")).toHaveValue("");
        expect(screen.queryByText("saved.xlsx")).not.toBeInTheDocument();
      }
      expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    }
  );
});
