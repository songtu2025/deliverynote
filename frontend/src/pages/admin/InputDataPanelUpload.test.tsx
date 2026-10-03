import { render, setupInputDataPanelTests, versions, getCatalogButton } from "./inputDataPanelTestSupport";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { message as staticMessage } from "antd";
import { describe, expect, it, vi } from "vitest";

import { jsonResponse } from "./positionDraftTestSupport";
import { InputDataPanel } from "./InputDataPanel";

setupInputDataPanelTests();

describe("InputDataPanel 上传校验", () => {
  it("shows supplier alias conflict rows returned by upload validation", async () => {
    const versionsWithSupplier = versions.map((version) => (version.id === 5 ? { ...version, active: true } : version));
    render(
      <InputDataPanel
        versions={versionsWithSupplier}
        loading={false}
        onVersionsChanged={vi.fn()}
        onOpenPositionDraft={vi.fn()}
      />
    );

    fireEvent.click(getCatalogButton("供应商资料"));
    await screen.findByText("瑞智雅|RIVBOS");
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "supplier-conflict" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(fileInput, {
      target: { files: [new File(["excel"], "supplier.xlsx", { type: "application/vnd.ms-excel" })] }
    });
    await screen.findByText("supplier.xlsx");
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    expect(await screen.findByText(/Excel 行 2, 3.*匹配歧义/)).toBeInTheDocument();
  });
  it.each([
    ["template", "导出模板", "unsupported.XLS", "valid.XLSX", "导出模板仅支持 .xlsx 文件"],
    ["inbound_template", "积加入库模板", "unsupported.xls", "valid.xlsx", "积加入库模板仅支持 .xlsx 文件"],
    ["product", "商品信息", "unsupported.csv", "valid.XLS", "仅支持 .xls、.xlsx 文件"],
    ["supplier", "供应商资料", "unsupported.xlsm", "valid.xls", "仅支持 .xls、.xlsx 文件"],
    ["position", "MSKU定位", "unsupported", "valid.XLSX", "仅支持 .xls、.xlsx 文件"]
  ] as const)(
    "rejects unsupported %s files and retains the name when corrected",
    async (kind, label, invalidName, validName, error) => {
      vi.mocked(fetch).mockImplementation(async (input, init) => {
        if (String(input).endsWith(`/api/input-versions/${kind}`) && init?.method === "POST") {
          return jsonResponse({ ...versions[6], id: 9, kind }, 201);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      });
      const onVersionsChanged = vi.fn();
      render(
        <InputDataPanel
          versions={[]}
          loading={false}
          onVersionsChanged={onVersionsChanged}
          onOpenPositionDraft={vi.fn()}
        />
      );
      fireEvent.click(getCatalogButton(label));
      fireEvent.click(screen.getByRole("button", { name: "上传首个版本" }));
      const name = `${kind}-version`;
      fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: name } });
      fireEvent.drop(screen.getByRole("button", { name: /拖放 Excel 到这里/ }), {
        dataTransfer: { files: [new File(["合成数据"], invalidName)] }
      });
      await screen.findByText(invalidName);
      const submit = screen.getByRole("button", { name: "校验并启用新版本" });
      fireEvent.click(submit);
      expect(await screen.findByText(error)).toBeInTheDocument();
      expect(fetch).not.toHaveBeenCalled();
      expect(onVersionsChanged).not.toHaveBeenCalled();
      expect(screen.getByLabelText("新版本名称")).toHaveValue(name);
      expect(screen.getByText(invalidName)).toBeInTheDocument();
      expect(submit).toBeEnabled();
      const valid = new File(["合成数据"], validName);
      fireEvent.change(document.querySelector<HTMLInputElement>('input[type="file"]')!, {
        target: { files: [valid] }
      });
      await screen.findByText(validName);
      expect(screen.queryByText(error)).not.toBeInTheDocument();
      expect(screen.getByLabelText("新版本名称")).toHaveValue(name);
      expect(fetch).not.toHaveBeenCalled();
      fireEvent.click(submit);
      await waitFor(() => expect(onVersionsChanged).toHaveBeenCalledOnce());
      expect(fetch).toHaveBeenCalledOnce();
      const body = vi.mocked(fetch).mock.calls[0][1]?.body as FormData;
      expect(body.get("name")).toBe(name);
      expect(body.get("activate")).toBe("true");
      expect(body.get("file")).toBe(valid);
    }
  );
  it("uploads a replacement only after explicit confirmation", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    fireEvent.change(screen.getByLabelText("新版本名称"), {
      target: { value: "product-replacement" }
    });
    const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: { files: [new File(["excel"], "replacement.xlsx", { type: "application/vnd.ms-excel" })] }
    });

    expect(await screen.findByText("replacement.xlsx")).toBeInTheDocument();
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
        )
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));

    await waitFor(() => {
      expect(onVersionsChanged).toHaveBeenCalledOnce();
    });
    const uploadCall = vi
      .mocked(fetch)
      .mock.calls.find(
        ([input, init]) => String(input).endsWith("/api/input-versions/product") && init?.method === "POST"
      );
    expect(uploadCall).toBeDefined();
    const body = uploadCall?.[1]?.body as FormData;
    expect(body.get("name")).toBe("product-replacement");
    expect(body.get("activate")).toBe("true");
    expect(body.get("file")).toBeInstanceOf(File);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    const feedback = await screen.findByText("商品信息已上传并启用，将用于新批次");
    expect(screen.getAllByText(feedback.textContent!)).toHaveLength(1);
    expect(feedback.closest<HTMLElement>(".ant-message")?.style.getPropertyValue("--notification-top")).toBe("64px");
    expect(staticMessage.success).not.toHaveBeenCalled();
  });
  it.each([false, true])("does not upload when the name or file is missing, hasName=%s", async (hasName) => {
    render(
      <InputDataPanel versions={versions} loading={false} onVersionsChanged={vi.fn()} onOpenPositionDraft={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: "更新资料" }));
    if (hasName) {
      fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "synthetic-no-file" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));
    expect(await screen.findByText(hasName ? "请选择要上传的 Excel 文件" : "请输入版本名称")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    expect(document.querySelector(".ant-message-notice")).not.toBeInTheDocument();
    if (hasName) expect(screen.getByLabelText("新版本名称")).toHaveValue("synthetic-no-file");
  });
});
