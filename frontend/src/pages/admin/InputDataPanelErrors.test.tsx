import {
  render,
  setupInputDataPanelTests,
  versions,
  getCatalogButton,
  confirmHistoryActivation
} from "./inputDataPanelTestSupport";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { message as staticMessage } from "antd";
import { describe, expect, it, vi } from "vitest";

import { api, ApiError, AUTH_EXPIRED_EVENT, download } from "../../api";
import { jsonResponse } from "./positionDraftTestSupport";
import { InputDataPanel } from "./InputDataPanel";

const state = setupInputDataPanelTests();

describe("InputDataPanel 失败恢复与登录失效", () => {
  it.each(["inspection", "upload", "activate", "download"])(
    "does not append local feedback for %s 401",
    async (operation) => {
      vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ id: 1 }));
      await api("/api/auth/me");
      const expired = vi.fn();
      window.addEventListener(AUTH_EXPIRED_EVENT, expired);
      const originalFetch = vi.mocked(fetch).getMockImplementation()!;
      vi.mocked(fetch).mockImplementation((input, init) => {
        if (operation === "inspection" || init?.method === "POST")
          return Promise.resolve(jsonResponse({ detail: "合成未登录" }, 401));
        return originalFetch(input, init);
      });
      vi.mocked(download).mockRejectedValue(new ApiError(401, "合成未登录"));
      const onVersionsChanged = vi.fn();
      try {
        render(
          <InputDataPanel
            versions={versions}
            loading={false}
            onVersionsChanged={onVersionsChanged}
            onOpenPositionDraft={vi.fn()}
          />
        );
        if (operation !== "inspection") await screen.findByText("PRODUCT-SKU");
        if (operation === "upload") {
          fireEvent.click(screen.getByText("更新资料", { selector: "button > span" }));
          fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "retry-version" } });
          fireEvent.change(document.querySelector('input[type="file"]')!, {
            target: { files: [new File(["synthetic"], "retry.xlsx")] }
          });
          await screen.findByText("retry.xlsx");
          fireEvent.click(screen.getByText("校验并启用新版本", { selector: "button > span" }));
        } else if (operation === "activate") {
          await confirmHistoryActivation();
        } else if (operation === "download") {
          fireEvent.click(screen.getByText("下载当前文件", { selector: "button > span" }));
          await waitFor(() => expect(download).toHaveBeenCalledOnce());
        }
        if (operation !== "download") await waitFor(() => expect(expired).toHaveBeenCalledOnce());
        await waitFor(() => expect(getCatalogButton("供应商资料")).toBeEnabled());
        expect(screen.queryByText("合成未登录")).not.toBeInTheDocument();
        expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
        expect(onVersionsChanged).not.toHaveBeenCalled();
        if (operation === "upload") expect(screen.getByLabelText("新版本名称")).toHaveValue("retry-version");
      } finally {
        window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
      }
    }
  );
  it("surfaces inspection and upload failures", async () => {
    state.failInspection = true;
    const onVersionsChanged = vi.fn();
    render(
      <InputDataPanel
        versions={versions}
        loading={false}
        onVersionsChanged={onVersionsChanged}
        onOpenPositionDraft={vi.fn()}
      />
    );

    expect(await screen.findByText("无法读取当前版本内容")).toBeInTheDocument();
    expect(screen.getByText("商品文件无法解析")).toBeInTheDocument();

    state.failUpload = true;
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "broken-product" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(fileInput!, {
      target: { files: [new File(["broken"], "broken.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("broken.xlsx");
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    expect(await screen.findByText("输入版本校验失败：缺少 SKU")).toBeInTheDocument();
    expect(onVersionsChanged).not.toHaveBeenCalled();
    const feedback = await screen.findByText("上传失败，请检查页面提示");
    expect(screen.getAllByText("上传失败，请检查页面提示")).toHaveLength(1);
    expect(feedback.closest<HTMLElement>(".ant-message")?.style.getPropertyValue("--notification-top")).toBe("64px");
    expect(staticMessage.error).not.toHaveBeenCalled();
    expect(screen.getByLabelText("新版本名称")).toHaveValue("broken-product");
    expect(screen.getByText("broken.xlsx")).toBeInTheDocument();

    fireEvent.click(getCatalogButton("供应商资料"));
    expect(screen.queryByText("输入版本校验失败：缺少 SKU")).not.toBeInTheDocument();
    fireEvent.click(getCatalogButton("商品信息"));
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    expect(screen.getByText("输入版本校验失败：缺少 SKU")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "synthetic-retry" } });
    const retryFileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(retryFileInput, { target: { files: [new File(["replacement"], "replacement.xlsx")] } });
    await screen.findByText("replacement.xlsx");
    expect(screen.queryByText("输入版本校验失败：缺少 SKU")).not.toBeInTheDocument();
    expect(screen.queryByText("broken.xlsx")).not.toBeInTheDocument();
    state.failUpload = false;
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));
    await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
