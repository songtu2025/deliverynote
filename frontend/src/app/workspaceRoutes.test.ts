import { describe, expect, it } from "vitest";

import { readWorkspaceRoute, workspacePath } from "./workspaceRoutes";
import type { WorkspaceRoute } from "./workspaceRoutes";

const cases: Array<[string, WorkspaceRoute, string]> = [
  ["/", { page: "batches", batchId: null }, "/batches"],
  ["/batches", { page: "batches", batchId: null }, "/batches"],
  ["/batches/7", { page: "batches", batchId: 7 }, "/batches/7"],
  ["/self-operated", { page: "self-operated", batchId: null }, "/self-operated"],
  ["/self-operated/7", { page: "self-operated", batchId: 7 }, "/self-operated/7"],
  ["/overreceipt", { page: "overreceipt", batchId: null }, "/overreceipt"],
  ["/admin", { page: "admin", batchId: null }, "/admin"],
  ["/batches/7///", { page: "batches", batchId: 7 }, "/batches/7"],
  ["/unknown", { page: "batches", batchId: null }, "/batches"],
  ["/batches/0", { page: "batches", batchId: null }, "/batches"]
];

describe("工作区路由契约", () => {
  it.each(cases)("保留 %s 的解析与规范路径", (path, route, canonicalPath) => {
    expect(readWorkspaceRoute(path)).toEqual(route);
    expect(workspacePath(route)).toBe(canonicalPath);
    expect(readWorkspaceRoute(canonicalPath)).toEqual(route);
  });
});
