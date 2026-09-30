import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PositionRowValues } from "./positionDraftApi";
import { baseRow, deferred } from "./positionDraftTestSupport";
import { rowValues, usePositionRowEditor } from "./usePositionRowEditor";

const form = vi.hoisted(() => ({ setFieldsValue: vi.fn(), resetFields: vi.fn(), validateFields: vi.fn() }));
vi.mock("antd", () => ({ Form: { useForm: () => [form] } }));

function editorView(busy = false) {
  const onBack = vi.fn();
  return { ...renderHook(({ busy }) => usePositionRowEditor(busy, onBack), { initialProps: { busy } }), onBack };
}

function startDirtyLeave(result: ReturnType<typeof editorView>["result"], leave: "close" | "back") {
  act(() => result.current.openEditRow(baseRow));
  act(() => result.current.markDirty());
  act(() => (leave === "back" ? result.current.requestBack() : result.current.requestClose()));
}

describe("usePositionRowEditor", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    form.validateFields.mockResolvedValue(rowValues(baseRow));
  });

  it("starts closed without touching an unmounted form", () => {
    const { result } = editorView();
    expect(result.current.open).toBe(false);
    expect(result.current.editingRow).toBeNull();
    act(() => result.current.reset());
    expect(form.resetFields).not.toHaveBeenCalled();
  });

  it("fills only editable fields and clears all five values for a new record", () => {
    const { result } = editorView();
    act(() => result.current.openEditRow(baseRow));
    expect(result.current.editingRow).toBe(baseRow);
    expect(form.setFieldsValue).toHaveBeenLastCalledWith(rowValues(baseRow));
    expect(Object.keys(rowValues(baseRow))).toHaveLength(5);
    act(() => result.current.openEditRow({ ...baseRow, id: 102, msku: "", stocking_position: "" }));
    expect(form.setFieldsValue).toHaveBeenLastCalledWith({ ...rowValues(baseRow), msku: "", stocking_position: "" });
    act(() => result.current.openNewRow());
    expect(result.current.open).toBe(true);
    expect(result.current.editingRow).toBeNull();
    expect(form.setFieldsValue).toHaveBeenLastCalledWith({
      store_site: "",
      jiaji_sku: "",
      msku: "",
      scale_position: "",
      stocking_position: ""
    });
    act(() => result.current.requestClose());
    expect(result.current.pendingLeave).toBeNull();
    expect(result.current.open).toBe(false);
  });

  it.each(["close", "back"] as const)("asks before dirty %s and keeps input when continuing", (leave) => {
    const { result, onBack } = editorView();
    startDirtyLeave(result, leave);
    expect(result.current.pendingLeave).toBe(leave);
    expect(onBack).not.toHaveBeenCalled();
    act(() => result.current.cancelLeave());
    expect(result.current.open).toBe(true);
    expect(result.current.editingRow).toBe(baseRow);
    expect(result.current.pendingLeave).toBeNull();
    expect(form.resetFields).not.toHaveBeenCalled();
    act(() => result.current.requestClose());
    expect(result.current.pendingLeave).toBe("close");
  });

  it.each(["close", "back"] as const)("resets confirmed dirty %s and navigates only for back", (leave) => {
    const { result, onBack } = editorView();
    startDirtyLeave(result, leave);
    act(() => result.current.confirmLeave());
    expect(result.current.open).toBe(false);
    expect(result.current.editingRow).toBeNull();
    expect(result.current.pendingLeave).toBeNull();
    expect(form.resetFields).toHaveBeenCalledOnce();
    expect(onBack).toHaveBeenCalledTimes(leave === "back" ? 1 : 0);
  });

  it("returns directly when there are no unsaved changes", () => {
    const { result, onBack } = editorView();
    act(() => result.current.requestBack());
    act(() => result.current.openNewRow());
    act(() => result.current.requestBack());
    expect(onBack).toHaveBeenCalledTimes(2);
    expect(result.current.pendingLeave).toBeNull();
  });

  it("uses the page busy state to block saving and all leave actions", async () => {
    const { result, rerender, onBack } = editorView();
    act(() => result.current.openNewRow());
    act(() => result.current.markDirty());
    act(() => result.current.requestClose());
    rerender({ busy: true });
    const write = vi.fn();
    await act(async () => expect(await result.current.save(write)).toBe(false));
    act(() => {
      result.current.cancelLeave();
      result.current.confirmLeave();
      result.current.requestBack();
      result.current.requestClose();
    });
    expect(result.current.open).toBe(true);
    expect(result.current.pendingLeave).toBe("close");
    expect(onBack).not.toHaveBeenCalled();
    expect(form.validateFields).not.toHaveBeenCalled();
    expect(write).not.toHaveBeenCalled();
  });

  it("does not write on validation failure and lets corrected input retry", async () => {
    const { result } = editorView();
    act(() => result.current.openNewRow());
    form.validateFields.mockRejectedValueOnce({ errorFields: ["store_site"] });
    const write = vi.fn().mockResolvedValue(true);
    await act(async () => expect(await result.current.save(write)).toBe(false));
    expect(write).not.toHaveBeenCalled();
    expect(result.current.open).toBe(true);
    expect(form.resetFields).not.toHaveBeenCalled();
    await act(async () => expect(await result.current.save(write)).toBe(true));
    expect(write).toHaveBeenCalledWith(rowValues(baseRow), null);
    expect(result.current.open).toBe(false);
  });

  it("preserves editing input on write failure and resets only after successful retry", async () => {
    const { result } = editorView();
    act(() => result.current.openEditRow(baseRow));
    act(() => result.current.markDirty());
    const write = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    await act(async () => expect(await result.current.save(write)).toBe(false));
    expect(result.current.open).toBe(true);
    expect(result.current.editingRow).toBe(baseRow);
    expect(form.resetFields).not.toHaveBeenCalled();
    await act(async () => expect(await result.current.save(write)).toBe(true));
    expect(write).toHaveBeenLastCalledWith(rowValues(baseRow), baseRow);
    expect(form.resetFields).toHaveBeenCalledOnce();
    expect(result.current.editingRow).toBeNull();
    act(() => result.current.openNewRow());
    act(() => result.current.requestClose());
    expect(result.current.pendingLeave).toBeNull();
  });

  it.each(["validation", "write"] as const)("prevents reentry and leaving during pending %s", async (stage) => {
    const { result, onBack } = editorView();
    act(() => result.current.openEditRow(baseRow));
    const validation = deferred<PositionRowValues>();
    const response = deferred<boolean>();
    form.validateFields.mockReturnValue(
      stage === "validation" ? validation.promise : Promise.resolve(rowValues(baseRow))
    );
    const write = vi.fn().mockReturnValue(response.promise);
    let saving!: Promise<boolean>;
    await act(async () => {
      saving = result.current.save(write);
    });
    await act(async () => expect(await result.current.save(write)).toBe(false));
    act(() => {
      result.current.requestClose();
      result.current.requestBack();
      result.current.confirmLeave();
    });
    expect(result.current.open).toBe(true);
    expect(onBack).not.toHaveBeenCalled();
    expect(form.validateFields).toHaveBeenCalledOnce();
    await act(async () => {
      validation.resolve(rowValues(baseRow));
      response.resolve(true);
      expect(await saving).toBe(true);
    });
    expect(write).toHaveBeenCalledOnce();
    expect(result.current.open).toBe(false);
  });

  it("clears the editor and outstanding leave confirmation when the session invalidates it", () => {
    const { result, onBack } = editorView();
    startDirtyLeave(result, "back");
    act(() => result.current.reset());
    expect(result.current.open).toBe(false);
    expect(result.current.editingRow).toBeNull();
    expect(result.current.pendingLeave).toBeNull();
    expect(onBack).not.toHaveBeenCalled();
    act(() => result.current.openNewRow());
    act(() => result.current.requestClose());
    expect(result.current.pendingLeave).toBeNull();
  });
});
