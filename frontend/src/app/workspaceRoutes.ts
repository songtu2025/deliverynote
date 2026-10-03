export type WorkspacePage = "batches" | "self-operated" | "overreceipt" | "admin";

export type WorkspaceRoute = {
  page: WorkspacePage;
  batchId: number | null;
};

export function readWorkspaceRoute(pathname: string): WorkspaceRoute {
  const normalizedPath = pathname.replace(/\/+$/, "") || "/";
  const batchMatch = normalizedPath.match(/^\/batches\/([1-9]\d*)$/);
  if (batchMatch) {
    return { page: "batches", batchId: Number(batchMatch[1]) };
  }
  const selfOperatedBatchMatch = normalizedPath.match(/^\/self-operated\/([1-9]\d*)$/);
  if (selfOperatedBatchMatch) {
    return { page: "self-operated", batchId: Number(selfOperatedBatchMatch[1]) };
  }
  if (normalizedPath === "/self-operated") {
    return { page: "self-operated", batchId: null };
  }
  if (normalizedPath === "/overreceipt") {
    return { page: "overreceipt", batchId: null };
  }
  if (normalizedPath === "/admin") {
    return { page: "admin", batchId: null };
  }
  return { page: "batches", batchId: null };
}

export function workspacePath(route: WorkspaceRoute): string {
  if (route.batchId !== null) {
    return route.page === "self-operated" ? `/self-operated/${route.batchId}` : `/batches/${route.batchId}`;
  }
  if (route.page === "self-operated") return "/self-operated";
  if (route.page === "overreceipt") return "/overreceipt";
  if (route.page === "admin") return "/admin";
  return "/batches";
}
