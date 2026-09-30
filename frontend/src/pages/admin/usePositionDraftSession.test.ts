import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PositionDraft } from "../../types";
import * as positionDraftApi from "./positionDraftApi";
import { baseDraft, deferred } from "./positionDraftTestSupport";
import { usePositionDraftSession } from "./usePositionDraftSession";

vi.mock("./positionDraftApi", () => ({ createOrResumeDraft: vi.fn(), getDraft: vi.fn() }));

function sessionView() {
  const onConflict = vi.fn();
  const view = renderHook(() => usePositionDraftSession(onConflict));
  return { ...view, onConflict };
}

async function openSession(view: ReturnType<typeof sessionView>) {
  await act(async () => {
    expect(await view.result.current.loadDraft()).toBe(true);
  });
}

describe("usePositionDraftSession", () => {
  beforeEach(() => {
    vi.mocked(positionDraftApi.createOrResumeDraft).mockResolvedValue({ ...baseDraft });
    vi.mocked(positionDraftApi.getDraft).mockResolvedValue({ ...baseDraft });
  });

  afterEach(() => vi.resetAllMocks());

  it("loads only on request and takes the server draft as the authority", async () => {
    const view = sessionView();
    expect(view.result.current.entryLoading).toBe(true);
    expect(view.result.current.draft).toBeNull();
    expect(positionDraftApi.createOrResumeDraft).not.toHaveBeenCalled();
    await openSession(view);
    expect(view.result.current.draft).toEqual(baseDraft);
    expect(view.result.current.getRevision()).toBe(3);
    expect(view.result.current.entryLoading).toBe(false);
  });

  it("retains a retry path after loading fails and clears conflicts when reloaded", async () => {
    const view = sessionView();
    vi.mocked(positionDraftApi.createOrResumeDraft).mockRejectedValueOnce(new Error("演示加载失败"));
    await act(async () => {
      expect(await view.result.current.loadDraft()).toBe(false);
    });
    expect(view.result.current.entryError).toBe("演示加载失败");
    expect(view.result.current.entryLoading).toBe(false);
    act(() => view.result.current.markConflict("演示协作冲突"));
    vi.mocked(positionDraftApi.createOrResumeDraft).mockResolvedValue({ ...baseDraft, revision: 11 });
    await openSession(view);
    expect(view.result.current.getRevision()).toBe(11);
    expect(view.result.current.entryError).toBeNull();
    expect(view.result.current.conflictMessage).toBeNull();
    expect(positionDraftApi.createOrResumeDraft).toHaveBeenCalledTimes(2);
  });

  it.each(["success", "failure"])("ignores an earlier load that finishes with %s", async (outcome) => {
    const old = deferred<PositionDraft>();
    vi.mocked(positionDraftApi.createOrResumeDraft).mockReturnValueOnce(
      old.promise.then((draft) => {
        if (outcome === "failure") throw new Error("演示旧请求失败");
        return draft;
      })
    );
    const view = sessionView();
    let oldLoad!: Promise<boolean>;
    act(() => {
      oldLoad = view.result.current.loadDraft();
    });
    vi.mocked(positionDraftApi.createOrResumeDraft).mockResolvedValue({ ...baseDraft, revision: 9 });
    await openSession(view);
    await act(async () => {
      old.resolve(baseDraft);
      expect(await oldLoad).toBe(false);
    });
    expect(view.result.current.getRevision()).toBe(9);
    expect(view.result.current.draft?.revision).toBe(9);
    expect(view.result.current.entryError).toBeNull();
    expect(view.result.current.entryLoading).toBe(false);
  });

  it("accepts the returned revision immediately and merges only authoritative summary fields", async () => {
    const view = sessionView();
    await openSession(view);
    const summary: PositionDraft = {
      ...baseDraft,
      revision: 8,
      base_version_name: "不得覆盖草稿基线",
      row_count: 40,
      modified_count: 5,
      updated_by: 9,
      updated_at: "2026-09-30T09:00:00",
      diff: { added: 2, modified: 3, deleted: 0, unchanged: 35 },
      active_version_id: 32,
      active_version_name: "演示新正式版本"
    };
    vi.mocked(positionDraftApi.getDraft).mockResolvedValue(summary);
    act(() => {
      view.result.current.acceptRevision(8);
      expect(view.result.current.getRevision()).toBe(8);
    });
    await waitFor(() => expect(view.result.current.draft?.updated_by).toBe(9));
    expect(view.result.current.draft).toMatchObject({
      revision: 8,
      row_count: 40,
      modified_count: 5,
      diff: summary.diff,
      updated_at: summary.updated_at,
      active_version_id: 32,
      base_version_name: baseDraft.base_version_name
    });
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it.each([{ revision: 2 }, { revision: 4, id: 99 }])("ignores unrelated or older metadata: %j", async (overrides) => {
    const view = sessionView();
    await openSession(view);
    vi.mocked(positionDraftApi.getDraft).mockResolvedValue({ ...baseDraft, ...overrides, row_count: 99 });
    await act(async () => view.result.current.acceptRevision(4));
    expect(view.result.current.draft).toMatchObject({ id: 7, revision: 4, row_count: 1 });
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it("marks newer metadata as a conflict without merging another editor's totals", async () => {
    const view = sessionView();
    await openSession(view);
    vi.mocked(positionDraftApi.getDraft).mockResolvedValue({ ...baseDraft, revision: 5, row_count: 99 });
    await act(async () => view.result.current.acceptRevision(4));
    expect(view.result.current.conflictMessage).toBe("草稿已被其他管理员更新，请刷新后重试");
    expect(view.result.current.draft).toMatchObject({ revision: 4, row_count: 1 });
    expect(view.onConflict).toHaveBeenCalledOnce();
    expect(view.onConflict).toHaveBeenCalledWith(view.result.current.conflictMessage);
  });

  it("does not roll back an accepted revision when its metadata refresh fails", async () => {
    const view = sessionView();
    await openSession(view);
    vi.mocked(positionDraftApi.getDraft).mockRejectedValue(new Error("演示摘要刷新失败"));
    await act(async () => view.result.current.acceptRevision(8));
    expect(view.result.current.getRevision()).toBe(8);
    expect(view.result.current.draft?.revision).toBe(8);
    expect(view.result.current.entryError).toBeNull();
    expect(view.result.current.conflictMessage).toBeNull();
    expect(positionDraftApi.getDraft).toHaveBeenCalledOnce();
  });

  it.each([
    { accepted: 8, late: 9 },
    { accepted: 4, late: 4 }
  ])("ignores earlier metadata regardless of revision: %j", async ({ accepted, late }) => {
    const old = deferred<PositionDraft>();
    const view = sessionView();
    await openSession(view);
    vi.mocked(positionDraftApi.getDraft)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ ...baseDraft, revision: accepted, row_count: 8 });
    act(() => view.result.current.acceptRevision(4));
    await act(async () => view.result.current.acceptRevision(accepted));
    await act(async () => old.resolve({ ...baseDraft, revision: late, row_count: 99 }));
    expect(view.result.current.draft).toMatchObject({ revision: accepted, row_count: 8 });
    expect(view.result.current.conflictMessage).toBeNull();
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it("ignores a pending load after unmount", async () => {
    const pending = deferred<PositionDraft>();
    vi.mocked(positionDraftApi.createOrResumeDraft).mockReturnValue(pending.promise);
    const view = sessionView();
    let loading!: Promise<boolean>;
    act(() => {
      loading = view.result.current.loadDraft();
    });
    view.unmount();
    pending.resolve(baseDraft);
    expect(await loading).toBe(false);
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it("ignores pending metadata after unmount without triggering conflict cleanup", async () => {
    const pending = deferred<PositionDraft>();
    const view = sessionView();
    await openSession(view);
    vi.mocked(positionDraftApi.getDraft).mockReturnValue(pending.promise);
    act(() => view.result.current.acceptRevision(4));
    view.unmount();
    await act(async () => pending.resolve({ ...baseDraft, revision: 5 }));
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it("records a published revision without starting a now-unneeded summary request", async () => {
    const view = sessionView();
    await openSession(view);
    act(() => view.result.current.recordRevision(12));
    expect(view.result.current.getRevision()).toBe(12);
    expect(positionDraftApi.getDraft).not.toHaveBeenCalled();
  });
});
