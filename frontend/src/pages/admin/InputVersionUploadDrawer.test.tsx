import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider, Form } from "antd";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InputVersionUploadDrawer } from "./InputVersionUploadDrawer";

type DrawerProps = Omit<ComponentProps<typeof InputVersionUploadDrawer>, "form">;

function drawerProps(): DrawerProps {
  return {
    kind: "product",
    hasActiveVersion: true,
    open: true,
    busy: false,
    uploading: false,
    files: [],
    error: null,
    onFileChange: vi.fn(),
    onSubmit: vi.fn(),
    onClose: vi.fn()
  };
}

function DrawerView(props: DrawerProps) {
  const [form] = Form.useForm<{ name: string }>();
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <InputVersionUploadDrawer {...props} form={form} />
    </ConfigProvider>
  );
}

describe("InputVersionUploadDrawer", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("上传抽屉不应自行发送请求"));
  });
  afterEach(() => {
    expect(fetch).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("limits the panel width to its inline container", () => {
    const { container } = render(<DrawerView {...drawerProps()} />);
    expect(container.querySelector(".ant-drawer-content-wrapper")).toHaveStyle({ width: "520px", maxWidth: "100%" });
  });

  it.each([
    ["product", true, "更新商品信息"],
    ["supplier", true, "更新供应商资料"],
    ["position", false, "上传MSKU定位"]
  ] as const)("shows the %s title and upload impact", (kind, hasActiveVersion, title) => {
    render(<DrawerView {...drawerProps()} kind={kind} hasActiveVersion={hasActiveVersion} />);
    expect(screen.getByRole("dialog", { name: title })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: hasActiveVersion ? "上传替换当前版本" : "上传首个版本" })
    ).toBeInTheDocument();
    expect(screen.getByText("仅用于新批次；已有批次不变。")).toBeInTheDocument();
    expect(screen.queryByText("供应商别名为可选列") !== null).toBe(kind === "supplier");
  });

  it("delegates file selection and explicit submission without uploading", async () => {
    const props = drawerProps();
    const { container } = render(<DrawerView {...props} />);
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    expect(fileInput).toHaveAttribute("accept", ".xls,.xlsx");
    expect(fileInput.multiple).toBe(false);
    const file = new File(["synthetic"], "synthetic.xlsx");
    fireEvent.change(fileInput, { target: { files: [file] } });
    await waitFor(() => expect(props.onFileChange).toHaveBeenCalledOnce());
    expect(vi.mocked(props.onFileChange).mock.calls[0][0].fileList[0].originFileObj).toBe(file);
    expect(props.onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "校验并启用新版本" }));
    expect(props.onSubmit).toHaveBeenCalledOnce();
  });

  it.each([
    ["purchase", ".xls,.xlsx", "仅支持 .xls、.xlsx 文件"],
    ["product", ".xls,.xlsx", "仅支持 .xls、.xlsx 文件"],
    ["supplier", ".xls,.xlsx", "仅支持 .xls、.xlsx 文件"],
    ["position", ".xls,.xlsx", "仅支持 .xls、.xlsx 文件"],
    ["template", ".xlsx", "导出模板仅支持 .xlsx 文件"],
    ["inbound_template", ".xlsx", "积加入库模板仅支持 .xlsx 文件"]
  ] as const)("uses the supported formats and hint for %s", (kind, accept, hint) => {
    const { container } = render(<DrawerView {...drawerProps()} kind={kind} />);
    expect(container.querySelector('input[type="file"]')).toHaveAttribute("accept", accept);
    expect(screen.getByText(`${hint}；选择后不会立即生效`)).toBeInTheDocument();
  });

  it("reflects parent-owned files and errors without clearing the name", () => {
    const props = drawerProps();
    props.files = [{ uid: "first", name: "first.xlsx" }];
    const view = render(<DrawerView {...props} />);
    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "synthetic-version" } });
    const error = '<img src=x onerror="window.__uiInjected=true">合成失败';
    view.rerender(<DrawerView {...props} error={error} />);
    expect(screen.getByText(error)).toBeInTheDocument();
    expect(screen.getByLabelText("新版本名称")).toHaveValue("synthetic-version");
    expect(screen.getByText("first.xlsx")).toBeInTheDocument();
    expect(view.container.querySelector("img")).toBeNull();
    view.rerender(<DrawerView {...props} files={[{ uid: "second", name: "second.xlsx" }]} />);
    expect(screen.queryByText(error)).not.toBeInTheDocument();
    expect(screen.queryByText("first.xlsx")).not.toBeInTheDocument();
    expect(screen.getByText("second.xlsx")).toBeInTheDocument();
    expect(screen.getByLabelText("新版本名称")).toHaveValue("synthetic-version");
  });

  it.each([false, true])("locks controls during a shared mutation, uploading=%s", (uploading) => {
    const props = drawerProps();
    const view = render(<DrawerView {...props} busy uploading={uploading} />);
    const submit = screen.getByRole("button", { name: "校验并启用新版本" });
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute("aria-busy", String(uploading));
    expect(screen.getByLabelText("新版本名称")).toBeDisabled();
    expect(view.container.querySelector('input[type="file"]')).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    fireEvent.click(submit);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape", keyCode: 27 });
    fireEvent.click(view.container.querySelector(".ant-drawer-mask")!);
    expect(props.onSubmit).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
    view.rerender(<DrawerView {...props} />);
    expect(submit).toBeEnabled();
    expect(submit).toHaveAttribute("aria-busy", "false");
    expect(screen.getByLabelText("新版本名称")).toBeEnabled();
  });

  it("clears the form on close while retaining parent-controlled files", async () => {
    const props = drawerProps();
    props.files = [{ uid: "retained", name: "retained.xlsx" }];
    const view = render(<DrawerView {...props} />);
    fireEvent.change(screen.getByLabelText("新版本名称"), { target: { value: "synthetic-name" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(props.onClose).toHaveBeenCalledOnce();
    view.rerender(<DrawerView {...props} open={false} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    view.rerender(<DrawerView {...props} />);
    expect(await screen.findByLabelText("新版本名称")).toHaveValue("");
    expect(screen.getByText("retained.xlsx")).toBeInTheDocument();
  });
});
