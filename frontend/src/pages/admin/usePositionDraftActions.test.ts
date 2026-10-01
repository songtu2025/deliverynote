import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import type { PositionDraft } from "../../types";
import * as positionDraftApi from "./positionDraftApi";
import { baseDraft, deferred } from "./positionDraftTestSupport";
import { usePositionDraftActions } from "./usePositionDraftActions";

vi.mock("./positionDraftApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./positionDraftApi")>()),
  downloadDraft: vi.fn(),
  discardDraft: vi.fn()
}));

function actionsView(
  initialProps: { draft: PositionDraft | null; disabled: boolean } = { draft: baseDraft, disabled: false }
) {
  const getRevision = vi.fn(() => 11);
  const onBusyChange = vi.fn();
  const onError = vi.fn();
  const onConflict = vi.fn();
  const onDiscarded = vi.fn();
  const view = renderHook(
    (props) => usePositionDraftActions({ ...props, getRevision, onBusyChange, onError, onConflict, onDiscarded }),
    { initialProps }
  );
  onConflict.mockImplementation(() => view.result.current.reset());
  return { ...view, getRevision, onBusyChange, onError, onConflict, onDiscarded };
}

describe("usePositionDraftActions", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(positionDraftApi.downloadDraft).mockResolvedValue();
    vi.mocked(positionDraftApi.discardDraft).mockResolvedValue({ ...baseDraft, status: "discarded", revision: 12 });
  });

  it("downloads the displayed revision and reports a local retryable error", async () => {
    const view = actionsView();
    vi.mocked(positionDraftApi.downloadDraft).mockRejectedValueOnce(new Error("演示下载失败"));
    await act(async () => view.result.current.download());
    expect(positionDraftApi.downloadDraft).toHaveBeenCalledWith(7, 3);
    expect(view.onError).toHaveBeenLastCalledWith("演示下载失败");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onBusyChange).not.toHaveBeenCalled();
    await act(async () => view.result.current.download());
    expect(positionDraftApi.downloadDraft).toHaveBeenCalledTimes(2);
    expect(view.onError).toHaveBeenLastCalledWith(null);
  });

  it.each([
    { draft: null, disabled: false },
    { draft: baseDraft, disabled: true }
  ])("does not discard an unavailable draft: %s", async (props) => {
    const view = actionsView(props);
    await act(async () => view.result.current.confirmDiscard());
    expect(positionDraftApi.discardDraft).not.toHaveBeenCalled();
    expect(view.onBusyChange).not.toHaveBeenCalled();
    expect(view.onDiscarded).not.toHaveBeenCalled();
  });

  it("does not download before a draft is available", async () => {
    const view = actionsView({ draft: null, disabled: false });
    await act(async () => view.result.current.download());
    expect(positionDraftApi.downloadDraft).not.toHaveBeenCalled();
    expect(view.onError).not.toHaveBeenCalled();
  });

  it("uses the current write revision and prevents duplicate confirmation and cancellation while pending", async () => {
    const response = deferred<PositionDraft>();
    vi.mocked(positionDraftApi.discardDraft).mockReturnValueOnce(response.promise);
    const view = actionsView();
    act(() => view.result.current.changeConfirmOpen(true));
    let pending!: Promise<void>;
    act(() => {
      pending = view.result.current.confirmDiscard();
      void view.result.current.confirmDiscard();
      view.result.current.changeConfirmOpen(false);
    });
    expect(positionDraftApi.discardDraft).toHaveBeenCalledOnce();
    expect(positionDraftApi.discardDraft).toHaveBeenCalledWith(7, 11);
    expect(view.result.current.confirmOpen).toBe(true);
    expect(view.onBusyChange.mock.calls).toEqual([["discard"]]);
    expect(view.onDiscarded).not.toHaveBeenCalled();
    await act(async () => {
      response.resolve({ ...baseDraft, status: "discarded", revision: 12 });
      await pending;
    });
    expect(view.result.current.confirmOpen).toBe(false);
    expect(view.onDiscarded).toHaveBeenCalledOnce();
    expect(view.onBusyChange.mock.calls).toEqual([["discard"], [null]]);
  });

  it("retains the confirmation after failure and permits retry with the same revision", async () => {
    vi.mocked(positionDraftApi.discardDraft).mockRejectedValueOnce(new Error("演示放弃失败"));
    const view = actionsView();
    act(() => view.result.current.changeConfirmOpen(true));
    await act(async () => view.result.current.confirmDiscard());
    act(() => view.result.current.changeConfirmOpen(false));
    expect(view.result.current.confirmOpen).toBe(true);
    expect(view.onError).toHaveBeenLastCalledWith("演示放弃失败");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onDiscarded).not.toHaveBeenCalled();
    await act(async () => view.result.current.confirmDiscard());
    expect(vi.mocked(positionDraftApi.discardDraft).mock.calls).toEqual([
      [7, 11],
      [7, 11]
    ]);
    expect(view.result.current.confirmOpen).toBe(false);
    expect(view.onDiscarded).toHaveBeenCalledOnce();
  });

  it.each(["draft_revision_conflict", "other_conflict"])("classifies a 409 by its code: %s", async (code) => {
    vi.mocked(positionDraftApi.discardDraft).mockRejectedValueOnce(new ApiError(409, "演示冲突", code));
    const view = actionsView();
    act(() => view.result.current.changeConfirmOpen(true));
    await act(async () => view.result.current.confirmDiscard());
    if (code === "draft_revision_conflict") {
      expect(view.onConflict).toHaveBeenCalledWith("演示冲突");
      expect(view.result.current.confirmOpen).toBe(false);
      expect(view.onError).not.toHaveBeenCalledWith("演示冲突");
    } else {
      expect(view.onConflict).not.toHaveBeenCalled();
      expect(view.onError).toHaveBeenLastCalledWith("演示冲突");
      expect(view.result.current.confirmOpen).toBe(true);
    }
    expect(view.onDiscarded).not.toHaveBeenCalled();
    expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
  });

  it.each(["success", "failure"])("ignores a late discard %s after unmounting", async (outcome) => {
    const response = deferred<PositionDraft>();
    vi.mocked(positionDraftApi.discardDraft).mockReturnValueOnce(
      response.promise.then((draft) => {
        if (outcome === "failure") throw new Error("演示迟到失败");
        return draft;
      })
    );
    const view = actionsView();
    let pending!: Promise<void>;
    act(() => {
      pending = view.result.current.confirmDiscard();
    });
    view.unmount();
    await act(async () => {
      response.resolve({ ...baseDraft, status: "discarded", revision: 12 });
      await pending;
    });
    expect(view.onDiscarded).not.toHaveBeenCalled();
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onError).not.toHaveBeenCalledWith("演示迟到失败");
    expect(view.onBusyChange.mock.calls).toEqual([["discard"]]);
  });

  it("ignores a late download failure after resetting the local operation", async () => {
    const response = deferred<void>();
    vi.mocked(positionDraftApi.downloadDraft).mockReturnValueOnce(
      response.promise.then(() => {
        throw new Error("演示旧下载失败");
      })
    );
    const view = actionsView();
    let pending!: Promise<void>;
    act(() => {
      pending = view.result.current.download();
      view.result.current.reset();
    });
    await act(async () => {
      response.resolve();
      await pending;
    });
    expect(view.onError).not.toHaveBeenCalledWith("演示旧下载失败");
    expect(view.onConflict).not.toHaveBeenCalled();
  });
});
