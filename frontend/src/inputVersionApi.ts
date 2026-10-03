import { api, download } from "./api";
import type { InputVersion, InputVersionInspection } from "./types";
import type { InputKind } from "./pages/admin/adminConstants";

export function getInputVersionInspection(versionId: number): Promise<InputVersionInspection> {
  return api<InputVersionInspection>(`/api/input-versions/${versionId}/inspection`);
}

export function uploadInputVersion(kind: InputKind, name: string, file: File): Promise<InputVersion> {
  const formData = new FormData();
  formData.append("name", name);
  formData.append("activate", "true");
  formData.append("file", file);
  return api<InputVersion>(`/api/input-versions/${kind}`, { method: "POST", body: formData });
}

export function activateInputVersion(versionId: number): Promise<InputVersion> {
  return api<InputVersion>(`/api/input-versions/${versionId}/activate`, { method: "POST" });
}

export function downloadInputVersion(version: InputVersion): Promise<void> {
  return download(`/api/input-versions/${version.id}/download`, version.original_name);
}
