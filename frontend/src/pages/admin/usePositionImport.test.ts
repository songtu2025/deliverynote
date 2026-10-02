import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import type { PositionImportPreview } from "../../types";
import * as positionDraftApi from "./positionDraftApi";
import { baseImportPreview, deferred } from "./positionDraftTestSupport";
import { usePositionImport } from "./usePositionImport";

vi.mock("./positionDraftApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./positionDraftApi")>()),
  previewImport: vi.fn(),
  applyImport: vi.fn()
}));

const file = new File(["合成数据"], "replacement.xlsx");

function importView(disabled = false, draftId: number | undefined = 7) {
  const onBusyChange = vi.fn();
  const onApplied = vi.fn();
  const onConflict = vi.fn();
  const getRevision = vi.fn(() => 3);
  const view = renderHook<ReturnType<typeof usePositionImport>, { disabled: boolean; draftId: number | undefined }>(
    ({ disabled, draftId }: { disabled: boolean; draftId: number | undefined }) =>
      usePositionImport({ disabled, draftId, getRevision, onBusyChange, onApplied, onConflict }),
    { initialProps: { disabled, draftId } }
  );
  onConflict.mockImplementation(() => view.result.current.reset());
  return { ...view, onBusyChange, onApplied, onConflict, getRevision };
}

async function preparePreview(view: ReturnType<typeof importView>) {
  await act(async () => expect(await view.result.current.previewFile(file)).toBeNull());
  return view;
}

function expectReset(view: ReturnType<typeof importView>) {
  expect(view.result.current).toMatchObject({ preview: null, fileName: "", error: null });
}

describe("usePositionImport", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(positionDraftApi.previewImport).mockResolvedValue(baseImportPreview);
    vi.mocked(positionDraftApi.applyImport).mockResolvedValue({ revision: 6, diff: baseImportPreview.diff });
  });

  it("previews server results without applying or changing revision", async () => {
    const view = await preparePreview(importView());
    expect(positionDraftApi.previewImport).toHaveBeenCalledWith(7, 3, file);
    expect(view.result.current.preview).toBe(baseImportPreview);
    expect(view.result.current.fileName).toBe(file.name);
    expect(view.result.current.error).toBeNull();
    expect(positionDraftApi.applyImport).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
    expect(view.onBusyChange.mock.calls).toEqual([["import-preview"], [null]]);
  });

  it.each(["disabled", "missing draft"])("rejects preview and apply when %s", async (reason) => {
    const view = importView(reason === "disabled");
    if (reason === "missing draft") view.rerender({ disabled: false, draftId: undefined });
    await act(async () => {
      expect(await view.result.current.previewFile(file)).toMatchObject({ message: "草稿当前不可修改" });
      await view.result.current.apply();
    });
    expect(positionDraftApi.previewImport).not.toHaveBeenCalled();
    expect(positionDraftApi.applyImport).not.toHaveBeenCalled();
    expect(view.onBusyChange).not.toHaveBeenCalled();
  });

  it("cancels without writing and clears the candidate before the next preview", async () => {
    const view = await preparePreview(importView());
    act(() => view.result.current.cancel());
    expectReset(view);
    await act(async () => view.result.current.apply());
    expect(positionDraftApi.applyImport).not.toHaveBeenCalled();
    const next = { ...baseImportPreview, token: "next-token", row_count: 9 };
    vi.mocked(positionDraftApi.previewImport).mockResolvedValueOnce(next);
    await act(async () => view.result.current.previewFile(new File(["新数据"], "next.xlsx")));
    expect(view.result.current.preview).toBe(next);
    expect(view.result.current.fileName).toBe("next.xlsx");
  });

  it.each([401, 403, 500])("handles preview failure %i without changing revision", async (status) => {
    const view = importView();
    const failure = new ApiError(status, "预览失败");
    vi.mocked(positionDraftApi.previewImport).mockRejectedValueOnce(failure);
    await act(async () => expect(await view.result.current.previewFile(file)).toBe(status === 401 ? false : failure));
    expect(view.result.current.error).toBe(status === 401 ? null : "预览失败");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
    expect(view.result.current.preview).toBeNull();
    expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
    await preparePreview(view);
    expect(view.result.current.error).toBeNull();
  });

  it("converts a non-Error preview failure to the existing fallback", async () => {
    const view = importView();
    vi.mocked(positionDraftApi.previewImport).mockRejectedValueOnce({ failed: true });
    await act(async () =>
      expect(await view.result.current.previewFile(file)).toMatchObject({ message: "Excel 预览失败" })
    );
    expect(view.result.current.error).toBe("Excel 预览失败");
  });

  it("applies the token with the current authoritative revision and resets after success", async () => {
    const view = await preparePreview(importView());
    view.getRevision.mockReturnValue(5);
    await act(async () => view.result.current.apply());
    expect(positionDraftApi.applyImport).toHaveBeenCalledWith(7, 5, baseImportPreview.token);
    expect(view.onApplied).toHaveBeenCalledExactlyOnceWith(6);
    expectReset(view);
    expect(view.onBusyChange.mock.calls.slice(-2)).toEqual([["import-apply"], [null]]);
  });

  it.each(["preview", "apply"] as const)("routes revision conflict during %s through the session", async (stage) => {
    const view = importView();
    if (stage === "apply") await preparePreview(view);
    const failure = new ApiError(409, "修订号已变化", "draft_revision_conflict");
    vi.mocked(
      stage === "preview" ? positionDraftApi.previewImport : positionDraftApi.applyImport
    ).mockRejectedValueOnce(failure);
    await act(async () => (stage === "preview" ? view.result.current.previewFile(file) : view.result.current.apply()));
    expect(view.onConflict).toHaveBeenCalledExactlyOnceWith(failure.message);
    expect(view.onApplied).not.toHaveBeenCalled();
    expectReset(view);
  });

  it.each([401, 403, 409, 422, 500])("preserves the candidate after apply failure %i", async (status) => {
    const view = await preparePreview(importView());
    vi.mocked(positionDraftApi.applyImport).mockRejectedValueOnce(new ApiError(status, "替换失败"));
    await act(async () => view.result.current.apply());
    expect(view.result.current.preview).toBe(baseImportPreview);
    expect(view.result.current.fileName).toBe(file.name);
    expect(view.result.current.error).toBe(status === 401 ? null : "替换失败");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
    act(() => view.result.current.clearError());
    expect(view.result.current.error).toBeNull();
    await act(async () => view.result.current.apply());
    expect(view.onApplied).toHaveBeenCalledExactlyOnceWith(6);
  });

  it("requires a new preview when the token was consumed after a failed apply", async () => {
    const view = await preparePreview(importView());
    vi.mocked(positionDraftApi.applyImport)
      .mockRejectedValueOnce(new ApiError(500, "替换失败"))
      .mockRejectedValueOnce(new ApiError(409, "请重新预览", "draft_import_preview_expired"));
    await act(async () => view.result.current.apply());
    await act(async () => view.result.current.apply());
    expect(view.result.current.preview).toBeNull();
    expect(view.result.current.fileName).toBe("");
    expect(view.result.current.error).toBe("请重新预览");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
    await act(async () => view.result.current.apply());
    expect(positionDraftApi.applyImport).toHaveBeenCalledTimes(2);
    await preparePreview(view);
    expect(view.result.current.error).toBeNull();
  });

  it.each(["preview", "apply"] as const)(
    "blocks duplicate requests and cancellation during pending %s",
    async (stage) => {
      const view = importView();
      const previewResponse = deferred<PositionImportPreview>();
      const applyResponse = deferred<Awaited<ReturnType<typeof positionDraftApi.applyImport>>>();
      if (stage === "apply") await preparePreview(view);
      vi.mocked(positionDraftApi.previewImport).mockReturnValue(previewResponse.promise);
      vi.mocked(positionDraftApi.applyImport).mockReturnValue(applyResponse.promise);
      let pending!: ReturnType<typeof view.result.current.previewFile> | Promise<void>;
      await act(async () => {
        pending = stage === "preview" ? view.result.current.previewFile(file) : view.result.current.apply();
        await view.result.current.apply();
        expect(await view.result.current.previewFile(file)).toBeInstanceOf(Error);
        view.result.current.cancel();
      });
      expect(view.result.current.preview).toBe(stage === "apply" ? baseImportPreview : null);
      expect(positionDraftApi.previewImport).toHaveBeenCalledTimes(1);
      expect(positionDraftApi.applyImport).toHaveBeenCalledTimes(stage === "apply" ? 1 : 0);
      await act(async () => {
        previewResponse.resolve(baseImportPreview);
        applyResponse.resolve({ revision: 6, diff: baseImportPreview.diff });
        await pending;
      });
      expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
    }
  );

  it("uses workspace disabling for an existing candidate and resets session-local state", async () => {
    const view = await preparePreview(importView());
    view.rerender({ disabled: true, draftId: 7 });
    await act(async () => view.result.current.apply());
    act(() => view.result.current.cancel());
    expect(view.result.current.preview).toBe(baseImportPreview);
    expect(positionDraftApi.applyImport).not.toHaveBeenCalled();
    act(() => view.result.current.reset());
    expectReset(view);
  });

  it.each(["preview", "apply"] as const)("ignores late %s responses after reset or unmount", async (stage) => {
    for (const cleanup of ["reset", "unmount"]) {
      for (const failure of [false, true]) {
        const view = importView();
        if (stage === "apply") await preparePreview(view);
        const response = deferred<void>();
        const request = stage === "preview" ? positionDraftApi.previewImport : positionDraftApi.applyImport;
        vi.mocked(request).mockImplementationOnce(async () => {
          await response.promise;
          if (failure) throw new ApiError(409, "旧响应冲突", "draft_revision_conflict");
          return { ...baseImportPreview, revision: 6 };
        });
        let pending!: Promise<unknown>;
        act(() => {
          pending = stage === "preview" ? view.result.current.previewFile(file) : view.result.current.apply();
        });
        act(() => (cleanup === "reset" ? view.result.current.reset() : view.unmount()));
        await act(async () => {
          response.resolve();
          await pending;
        });
        if (cleanup === "reset") expectReset(view);
        expect(view.onApplied).not.toHaveBeenCalled();
        expect(view.onConflict).not.toHaveBeenCalled();
        if (cleanup === "unmount") expect(view.onBusyChange).not.toHaveBeenLastCalledWith(null);
        view.unmount();
      }
    }
  });
});
