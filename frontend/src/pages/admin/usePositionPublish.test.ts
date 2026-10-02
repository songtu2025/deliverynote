import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import type { PositionDraftValidation } from "../../types";
import * as positionDraftApi from "./positionDraftApi";
import { basePositionVersion, baseValidation, deferred } from "./positionDraftTestSupport";
import { usePositionPublish } from "./usePositionPublish";

vi.mock("./positionDraftApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./positionDraftApi")>()),
  validateDraft: vi.fn(),
  publishDraft: vi.fn()
}));

const published = { ...basePositionVersion, id: 32, draft_revision: 4, draft_status: "published" as const };

function publishView(disabled = false, draftId: number | undefined = 7) {
  const onBusyChange = vi.fn();
  const onValidationError = vi.fn();
  const onPublished = vi.fn();
  const onConflict = vi.fn();
  const getRevision = vi.fn(() => 3);
  const view = renderHook<ReturnType<typeof usePositionPublish>, { disabled: boolean; draftId: number | undefined }>(
    ({ disabled, draftId }: { disabled: boolean; draftId: number | undefined }) =>
      usePositionPublish({ draftId, disabled, getRevision, onBusyChange, onValidationError, onPublished, onConflict }),
    { initialProps: { disabled, draftId } }
  );
  onConflict.mockImplementation(() => view.result.current.reset());
  return { ...view, onBusyChange, onValidationError, onPublished, onConflict, getRevision };
}

async function preparePublish(view = publishView()) {
  await act(async () => view.result.current.open());
  return view;
}

function expectReset(view: ReturnType<typeof publishView>) {
  expect(view.result.current).toMatchObject({
    validation: null,
    name: "",
    nameError: null,
    error: null,
    warningsConfirmed: false,
    blocked: true
  });
}

describe("usePositionPublish", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(positionDraftApi.validateDraft).mockResolvedValue(baseValidation);
    vi.mocked(positionDraftApi.publishDraft).mockResolvedValue(published);
  });

  it("opens authoritative validation without publishing or recording a revision", async () => {
    const view = await preparePublish();
    expect(positionDraftApi.validateDraft).toHaveBeenCalledExactlyOnceWith(7);
    expect(view.result.current.validation).toBe(baseValidation);
    expect(view.result.current.name).toMatch(/^position-\d{8}-\d{4}$/);
    expect(view.result.current.blocked).toBe(false);
    expect(view.onBusyChange.mock.calls).toEqual([["validate"], [null]]);
    expect(positionDraftApi.publishDraft).not.toHaveBeenCalled();
    expect(view.onPublished).not.toHaveBeenCalled();
  });

  it.each(["disabled", "missing draft"])("blocks all requests when %s", async (reason) => {
    const view = publishView(reason === "disabled", reason === "missing draft" ? undefined : 7);
    if (reason === "missing draft") view.rerender({ disabled: false, draftId: undefined });
    await act(async () => {
      await view.result.current.open();
      await view.result.current.publish();
    });
    expect(positionDraftApi.validateDraft).not.toHaveBeenCalled();
    expect(positionDraftApi.publishDraft).not.toHaveBeenCalled();
    expect(view.onBusyChange).not.toHaveBeenCalled();
  });

  it.each(["errors", "warnings", "blank name"])("does not publish with %s", async (reason) => {
    vi.mocked(positionDraftApi.validateDraft).mockResolvedValue({
      ...baseValidation,
      error_count: reason === "errors" ? 1 : 0,
      warning_count: reason === "warnings" ? 1 : 0
    });
    const view = await preparePublish();
    if (reason === "blank name") act(() => view.result.current.changeName("  "));
    expect(view.result.current.blocked).toBe(true);
    await act(async () => view.result.current.publish());
    expect(positionDraftApi.publishDraft).not.toHaveBeenCalled();
  });

  it("publishes the validated revision, trimmed name and confirmed warnings exactly once", async () => {
    vi.mocked(positionDraftApi.validateDraft).mockResolvedValue({ ...baseValidation, warning_count: 1 });
    const view = await preparePublish();
    act(() => {
      view.result.current.changeName("  new-name  ");
      view.result.current.confirmWarnings(true);
    });
    await act(async () => view.result.current.publish());
    expect(positionDraftApi.publishDraft).toHaveBeenCalledExactlyOnceWith(7, {
      revision: 3,
      name: "new-name",
      confirm_warnings: true
    });
    expect(view.onPublished).toHaveBeenCalledExactlyOnceWith(published);
    expect(view.onBusyChange.mock.calls.slice(-2)).toEqual([["publish"], [null]]);
    expectReset(view);
    await act(async () => view.result.current.publish());
    expect(positionDraftApi.publishDraft).toHaveBeenCalledTimes(1);
  });

  it("cancels without writing and requires fresh validation and warning confirmation on reopening", async () => {
    vi.mocked(positionDraftApi.validateDraft).mockResolvedValue({ ...baseValidation, warning_count: 1 });
    const view = await preparePublish();
    act(() => {
      view.result.current.changeName("old-name");
      view.result.current.confirmWarnings(true);
      view.result.current.cancel();
    });
    expectReset(view);
    await preparePublish(view);
    expect(view.result.current.warningsConfirmed).toBe(false);
    expect(view.result.current.name).not.toBe("old-name");
    expect(view.result.current.blocked).toBe(true);
    expect(positionDraftApi.publishDraft).not.toHaveBeenCalled();
    expect(positionDraftApi.validateDraft).toHaveBeenCalledTimes(2);
  });

  it.each([401, 403, 500])("handles validation failure %i and permits retry", async (status) => {
    vi.mocked(positionDraftApi.validateDraft).mockRejectedValueOnce(new ApiError(status, "校验失败"));
    const view = await preparePublish();
    if (status === 401) expect(view.onValidationError).not.toHaveBeenCalled();
    else expect(view.onValidationError).toHaveBeenCalledExactlyOnceWith("校验失败");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onPublished).not.toHaveBeenCalled();
    expectReset(view);
    await preparePublish(view);
    expect(view.result.current.validation).toBe(baseValidation);
    expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
  });

  it.each(["response", "during request", "before publish"])("rejects stale validation %s", async (stage) => {
    const view = publishView();
    if (stage === "response")
      vi.mocked(positionDraftApi.validateDraft).mockResolvedValueOnce({ ...baseValidation, revision: 4 });
    if (stage === "during request")
      vi.mocked(positionDraftApi.validateDraft).mockImplementationOnce(async () => {
        view.getRevision.mockReturnValue(4);
        return { ...baseValidation, revision: 4 };
      });
    await preparePublish(view);
    if (stage === "before publish") {
      view.getRevision.mockReturnValue(4);
      await act(async () => view.result.current.publish());
    }
    expect(view.onConflict).toHaveBeenCalledExactlyOnceWith("草稿已由其他管理员修改，请刷新后重试", "revision");
    expect(positionDraftApi.publishDraft).not.toHaveBeenCalled();
    expectReset(view);
  });

  it.each(["validate", "publish"] as const)("routes revision conflict during %s to the session", async (stage) => {
    const view = publishView();
    if (stage === "publish") await preparePublish(view);
    vi.mocked(
      stage === "validate" ? positionDraftApi.validateDraft : positionDraftApi.publishDraft
    ).mockRejectedValueOnce(new ApiError(409, "草稿已更新", "draft_revision_conflict"));
    await act(async () => (stage === "validate" ? view.result.current.open() : view.result.current.publish()));
    expect(view.onConflict).toHaveBeenCalledExactlyOnceWith("草稿已更新", "revision");
    expectReset(view);
    expect(view.onPublished).not.toHaveBeenCalled();
  });

  it("distinguishes base-version expiry from a revision conflict", async () => {
    const view = await preparePublish();
    vi.mocked(positionDraftApi.publishDraft).mockRejectedValueOnce(
      new ApiError(409, "请放弃当前草稿后重新开始", "draft_base_version_changed")
    );
    await act(async () => view.result.current.publish());
    expect(view.onConflict).toHaveBeenCalledExactlyOnceWith("请放弃当前草稿后重新开始", "base");
    expectReset(view);
    expect(view.onPublished).not.toHaveBeenCalled();
  });

  it("keeps a duplicate name editable and clears its field error before retry", async () => {
    const view = await preparePublish();
    vi.mocked(positionDraftApi.publishDraft).mockRejectedValueOnce(
      new ApiError(409, "版本名称已存在", "input_version_name_exists")
    );
    act(() => view.result.current.changeName("duplicate"));
    await act(async () => view.result.current.publish());
    expect(view.result.current).toMatchObject({ name: "duplicate", nameError: "版本名称已存在", error: null });
    expect(view.onConflict).not.toHaveBeenCalled();
    act(() => view.result.current.changeName("unique"));
    expect(view.result.current.nameError).toBeNull();
    await act(async () => view.result.current.publish());
    expect(view.onPublished).toHaveBeenCalledOnce();
  });

  it.each([400, 401, 403, 409, 422, 500])(
    "preserves the name and warning confirmation after failure %i",
    async (status) => {
      vi.mocked(positionDraftApi.validateDraft).mockResolvedValue({ ...baseValidation, warning_count: 1 });
      const view = await preparePublish();
      act(() => {
        view.result.current.changeName("keep-name");
        view.result.current.confirmWarnings(true);
      });
      vi.mocked(positionDraftApi.publishDraft).mockRejectedValueOnce(new ApiError(status, "发布失败"));
      await act(async () => view.result.current.publish());
      expect(view.result.current).toMatchObject({
        name: "keep-name",
        error: status === 401 ? null : "发布失败",
        warningsConfirmed: true
      });
      expect(view.result.current.validation).not.toBeNull();
      expect(view.onPublished).not.toHaveBeenCalled();
      expect(view.onConflict).not.toHaveBeenCalled();
      await act(async () => view.result.current.publish());
      expect(view.onPublished).toHaveBeenCalledOnce();
    }
  );

  it.each(["validate", "publish"] as const)(
    "blocks reentry, cancellation and input changes during pending %s",
    async (stage) => {
      const view = publishView();
      const validationResponse = deferred<PositionDraftValidation>();
      const publishResponse = deferred<typeof published>();
      if (stage === "publish") await preparePublish(view);
      vi.mocked(positionDraftApi.validateDraft).mockReturnValue(validationResponse.promise);
      vi.mocked(positionDraftApi.publishDraft).mockReturnValue(publishResponse.promise);
      const name = view.result.current.name;
      let pending!: Promise<void>;
      await act(async () => {
        pending = stage === "validate" ? view.result.current.open() : view.result.current.publish();
        await view.result.current.open();
        await view.result.current.publish();
        view.result.current.cancel();
        view.result.current.changeName("ignored");
        view.result.current.confirmWarnings(true);
      });
      expect(positionDraftApi.validateDraft).toHaveBeenCalledTimes(1);
      expect(positionDraftApi.publishDraft).toHaveBeenCalledTimes(stage === "publish" ? 1 : 0);
      expect(view.result.current.name).toBe(name);
      expect(view.result.current.warningsConfirmed).toBe(false);
      await act(async () => {
        validationResponse.resolve(baseValidation);
        publishResponse.resolve(published);
        await pending;
      });
      expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
    }
  );

  it.each([
    ["validate", "reset"],
    ["validate", "unmount"],
    ["publish", "reset"],
    ["publish", "unmount"]
  ])("ignores a late %s response after %s", async (stage, cleanup) => {
    const response = deferred<PositionDraftValidation>();
    const publishResponse = deferred<typeof published>();
    const view = publishView();
    if (stage === "publish") await preparePublish(view);
    vi.mocked(positionDraftApi.validateDraft).mockReturnValueOnce(response.promise);
    vi.mocked(positionDraftApi.publishDraft).mockReturnValueOnce(publishResponse.promise);
    let pending!: Promise<void>;
    act(() => {
      pending = stage === "validate" ? view.result.current.open() : view.result.current.publish();
    });
    act(() => (cleanup === "reset" ? view.result.current.reset() : view.unmount()));
    await act(async () => {
      response.resolve(baseValidation);
      publishResponse.resolve(published);
      await pending;
    });
    if (cleanup === "reset") expectReset(view);
    expect(view.onPublished).not.toHaveBeenCalled();
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it("uses workspace disabling for existing validation", async () => {
    const view = await preparePublish();
    view.rerender({ disabled: true, draftId: 7 });
    await act(async () => view.result.current.publish());
    expect(view.result.current.blocked).toBe(true);
    expect(positionDraftApi.publishDraft).not.toHaveBeenCalled();
    act(() => view.result.current.reset());
    expectReset(view);
  });
});
