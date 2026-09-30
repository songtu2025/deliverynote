import type { PositionDraft } from "../../types";

export interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

export function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

export const baseDraft: PositionDraft = {
  id: 7,
  kind: "position",
  base_version_id: 31,
  base_version_name: "position-current",
  active_version_id: 31,
  active_version_name: "position-current",
  status: "editing",
  revision: 3,
  created_by: 1,
  updated_by: 2,
  created_at: "2026-07-21T09:10:00",
  updated_at: "2026-07-21T10:30:00",
  row_count: 1,
  modified_count: 0,
  diff: { added: 0, modified: 0, deleted: 0, unchanged: 1 },
  issues: [],
  error_count: 0,
  warning_count: 0,
  valid: true
};
