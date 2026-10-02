import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api";
import * as positionDraftApi from "./positionDraftApi";
import { baseRow, deferred } from "./positionDraftTestSupport";
import { rowValues } from "./usePositionRowEditor";
import { usePositionRowMutations } from "./usePositionRowMutations";

vi.mock("./positionDraftApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./positionDraftApi")>()),
  createRow: vi.fn(),
  updateRow: vi.fn(),
  deleteRow: vi.fn(),
  deleteRows: vi.fn()
}));

type MutationFlow = ReturnType<typeof usePositionRowMutations>;
const values = rowValues(baseRow);
const cases = [
  {
    name: "create",
    call: (flow: MutationFlow) => flow.save(values, null),
    api: "createRow",
    busy: "save",
    args: [7, { revision: 3, ...values }],
    message: "记录已保存"
  },
  {
    name: "update",
    call: (flow: MutationFlow) => flow.save(values, baseRow),
    api: "updateRow",
    busy: "save",
    args: [7, 101, { revision: 3, ...values }],
    message: "记录已保存"
  },
  {
    name: "copy",
    call: (flow: MutationFlow) => flow.copy(baseRow),
    api: "createRow",
    busy: "copy",
    args: [7, { revision: 3, ...values }],
    message: "记录已复制到服务器草稿"
  },
  {
    name: "delete",
    call: (flow: MutationFlow) => flow.deleteRow(baseRow),
    api: "deleteRow",
    busy: "delete",
    args: [7, 101, 3],
    message: "记录已从服务器草稿删除"
  },
  {
    name: "bulk delete",
    call: (flow: MutationFlow) => flow.bulkDelete([101, 102]),
    api: "deleteRows",
    busy: "bulk-delete",
    args: [7, 3, [101, 102]],
    message: "已删除 2 条草稿记录"
  }
] as const;
const apiMethods = ["createRow", "updateRow", "deleteRow", "deleteRows"] as const;

function mutationView(
  initialProps: { disabled: boolean; draftId: number | undefined } = { disabled: false, draftId: 7 }
) {
  let revision = 3;
  const getRevision = vi.fn(() => revision);
  const onBusyChange = vi.fn();
  const onApplied = vi.fn((nextRevision: number) => {
    revision = nextRevision;
  });
  const onError = vi.fn();
  const onConflict = vi.fn();
  const view = renderHook(
    ({ disabled, draftId }) =>
      usePositionRowMutations({
        disabled,
        draftId,
        getRevision,
        onBusyChange,
        onApplied,
        onError,
        onConflict
      }),
    { initialProps }
  );
  onConflict.mockImplementation(() => view.result.current.reset());
  return { ...view, getRevision, onBusyChange, onApplied, onError, onConflict };
}

describe("usePositionRowMutations", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(positionDraftApi.createRow).mockResolvedValue({ row: baseRow, revision: 9 });
    vi.mocked(positionDraftApi.updateRow).mockResolvedValue({ row: baseRow, revision: 9 });
    vi.mocked(positionDraftApi.deleteRow).mockResolvedValue({ row_id: 101, revision: 9 });
    vi.mocked(positionDraftApi.deleteRows).mockResolvedValue({ deleted_ids: [101, 102], revision: 9 });
  });

  it.each(cases)("sends the $name contract and accepts only the returned revision", async (scenario) => {
    const view = mutationView();
    let applied = false;
    await act(async () => {
      applied = await scenario.call(view.result.current);
    });
    expect(applied).toBe(true);
    expect(positionDraftApi[scenario.api]).toHaveBeenCalledExactlyOnceWith(...scenario.args);
    expect(view.onApplied).toHaveBeenCalledExactlyOnceWith(9, scenario.message);
    expect(view.getRevision()).toBe(9);
    expect(view.onBusyChange.mock.calls).toEqual([[scenario.busy], [null]]);
    expect(view.onError).not.toHaveBeenCalled();
    expect(view.onConflict).not.toHaveBeenCalled();
    await act(async () => {
      await view.result.current.deleteRow(baseRow);
    });
    expect(positionDraftApi.deleteRow).toHaveBeenLastCalledWith(7, 101, 9);
  });

  it.each(cases)("blocks $name while disabled or without a draft", async (scenario) => {
    const view = mutationView({ disabled: true, draftId: 7 });
    await act(async () => {
      expect(await scenario.call(view.result.current)).toBe(false);
    });
    view.rerender({ disabled: false, draftId: undefined });
    await act(async () => {
      expect(await scenario.call(view.result.current)).toBe(false);
    });
    apiMethods.forEach((name) => expect(positionDraftApi[name]).not.toHaveBeenCalled());
    expect(view.onBusyChange).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
  });

  it("does not submit an empty selection", async () => {
    const view = mutationView();
    await act(async () => {
      expect(await view.result.current.bulkDelete([])).toBe(false);
    });
    expect(positionDraftApi.deleteRows).not.toHaveBeenCalled();
    expect(view.onBusyChange).not.toHaveBeenCalled();
  });

  it.each(cases)("blocks simultaneous record writes while $name is pending", async (scenario) => {
    const result = { row: baseRow, row_id: 101, deleted_ids: [101, 102], revision: 9 };
    const response = deferred<typeof result>();
    vi.mocked(positionDraftApi[scenario.api]).mockReturnValueOnce(response.promise);
    const view = mutationView();
    let pending: Promise<boolean> = Promise.resolve(false);
    await act(async () => {
      pending = scenario.call(view.result.current);
      for (const duplicate of cases) expect(await duplicate.call(view.result.current)).toBe(false);
    });
    expect(apiMethods.reduce((count, name) => count + vi.mocked(positionDraftApi[name]).mock.calls.length, 0)).toBe(1);
    expect(view.onApplied).not.toHaveBeenCalled();
    await act(async () => {
      response.resolve(result);
      expect(await pending).toBe(true);
    });
    expect(view.onApplied).toHaveBeenCalledOnce();
    expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
  });

  it.each(cases)("routes $name revision conflicts to the session without applying a revision", async (scenario) => {
    vi.mocked(positionDraftApi[scenario.api]).mockRejectedValueOnce(
      new ApiError(409, "草稿已更新", "draft_revision_conflict")
    );
    const view = mutationView();
    await act(async () => {
      expect(await scenario.call(view.result.current)).toBe(false);
    });
    expect(view.onConflict).toHaveBeenCalledExactlyOnceWith("草稿已更新");
    expect(view.onError).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
    expect(view.getRevision()).toBe(3);
    expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
  });

  it.each([400, 401, 403, 409, 500])("handles failure %i and permits retry with the same revision", async (status) => {
    vi.mocked(positionDraftApi.createRow).mockRejectedValueOnce(new ApiError(status, "记录写入失败"));
    const view = mutationView();
    await act(async () => {
      expect(await view.result.current.copy(baseRow)).toBe(false);
    });
    if (status === 401) expect(view.onError).not.toHaveBeenCalled();
    else expect(view.onError).toHaveBeenCalledExactlyOnceWith("记录写入失败");
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.onApplied).not.toHaveBeenCalled();
    expect(view.getRevision()).toBe(3);
    await act(async () => {
      expect(await view.result.current.copy(baseRow)).toBe(true);
    });
    expect(vi.mocked(positionDraftApi.createRow).mock.calls.map(([, payload]) => payload.revision)).toEqual([3, 3]);
    expect(view.onApplied).toHaveBeenCalledOnce();
  });

  it("does not treat a revision error code on a 500 response as a collaboration conflict", async () => {
    vi.mocked(positionDraftApi.deleteRow).mockRejectedValueOnce(
      new ApiError(500, "删除失败", "draft_revision_conflict")
    );
    const view = mutationView();
    await act(async () => {
      expect(await view.result.current.deleteRow(baseRow)).toBe(false);
    });
    expect(view.onError).toHaveBeenCalledExactlyOnceWith("删除失败");
    expect(view.onConflict).not.toHaveBeenCalled();
  });

  it("uses the existing fallback for an unknown failure and releases the busy state", async () => {
    vi.mocked(positionDraftApi.createRow).mockRejectedValueOnce(null);
    const view = mutationView();
    await act(async () => {
      expect(await view.result.current.save(values, null)).toBe(false);
    });
    expect(view.onError).toHaveBeenCalledExactlyOnceWith("记录已保存失败");
    expect(view.onBusyChange).toHaveBeenLastCalledWith(null);
  });

  it.each([
    ["reset", "success"],
    ["reset", "failure"],
    ["unmount", "success"],
    ["unmount", "failure"]
  ])("%s invalidation ignores a late %s response", async (cleanup, outcome) => {
    const response = deferred<Awaited<ReturnType<typeof positionDraftApi.createRow>>>();
    vi.mocked(positionDraftApi.createRow).mockImplementationOnce(async () => {
      const result = await response.promise;
      if (outcome === "failure") throw new ApiError(409, "旧草稿冲突", "draft_revision_conflict");
      return result;
    });
    const view = mutationView();
    let pending: Promise<boolean> = Promise.resolve(false);
    act(() => {
      pending = view.result.current.copy(baseRow);
    });
    act(() => {
      if (cleanup === "reset") view.result.current.reset();
      else view.unmount();
    });
    if (cleanup === "reset") {
      await act(async () => {
        expect(await view.result.current.copy(baseRow)).toBe(false);
      });
    }
    await act(async () => {
      response.resolve({ row: baseRow, revision: 9 });
      expect(await pending).toBe(false);
    });
    expect(view.onApplied).not.toHaveBeenCalled();
    expect(view.onError).not.toHaveBeenCalled();
    expect(view.onConflict).not.toHaveBeenCalled();
    expect(view.getRevision()).toBe(3);
    if (cleanup === "reset") {
      await act(async () => {
        expect(await view.result.current.copy(baseRow)).toBe(true);
      });
    }
  });
});
