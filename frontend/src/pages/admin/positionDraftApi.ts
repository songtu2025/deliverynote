import { api, download } from "../../api";
import type {
  InputVersion,
  PositionDiff,
  PositionDraft,
  PositionDraftRow,
  PositionDraftRowsPage,
  PositionDraftValidation,
  PositionImportPreview
} from "../../types";

export type PositionRowValues = Pick<
  PositionDraftRow,
  "store_site" | "jiaji_sku" | "msku" | "scale_position" | "stocking_position"
>;

export interface PositionRevisionResponse {
  revision: number;
}

interface RowMutationPayload extends PositionRowValues, PositionRevisionResponse {}
interface RowMutationResponse extends PositionRevisionResponse {
  row: PositionDraftRow;
}
interface PublishPayload extends PositionRevisionResponse {
  name: string;
  confirm_warnings: boolean;
}
interface PublishResponse extends InputVersion {
  draft_revision: number;
  draft_status: PositionDraft["status"];
}
interface RowsQuery {
  offset: number;
  limit: number;
  search?: string;
  site?: string;
  scale_position?: string;
  only_errors?: boolean;
  only_modified?: boolean;
}

export function createOrResumeDraft(): Promise<PositionDraft> {
  return api<PositionDraft>("/api/input-drafts/position", { method: "POST" });
}

export function getDraft(): Promise<PositionDraft> {
  return api<PositionDraft>("/api/input-drafts/position");
}

export function listRows(draftId: number, query: RowsQuery): Promise<PositionDraftRowsPage> {
  const params = new URLSearchParams({ offset: String(query.offset), limit: String(query.limit) });
  if (query.search?.trim()) params.set("search", query.search.trim());
  if (query.site?.trim()) params.set("site", query.site.trim());
  if (query.scale_position?.trim()) params.set("scale_position", query.scale_position.trim());
  if (query.only_errors) params.set("only_errors", "true");
  if (query.only_modified) params.set("only_modified", "true");
  return api<PositionDraftRowsPage>(`/api/input-drafts/${draftId}/rows?${params.toString()}`);
}

export function createRow(draftId: number, values: RowMutationPayload): Promise<RowMutationResponse> {
  return api<RowMutationResponse>(`/api/input-drafts/${draftId}/rows`, {
    method: "POST",
    body: JSON.stringify(values)
  });
}

export function updateRow(draftId: number, rowId: number, values: RowMutationPayload): Promise<RowMutationResponse> {
  return api<RowMutationResponse>(`/api/input-drafts/${draftId}/rows/${rowId}`, {
    method: "PUT",
    body: JSON.stringify(values)
  });
}

export function deleteRow(
  draftId: number,
  rowId: number,
  revision: number
): Promise<PositionRevisionResponse & { row_id: number }> {
  return api<PositionRevisionResponse & { row_id: number }>(`/api/input-drafts/${draftId}/rows/${rowId}`, {
    method: "DELETE",
    body: JSON.stringify({ revision })
  });
}

export function deleteRows(
  draftId: number,
  revision: number,
  rowIds: number[]
): Promise<PositionRevisionResponse & { deleted_ids: number[] }> {
  return api<PositionRevisionResponse & { deleted_ids: number[] }>(`/api/input-drafts/${draftId}/rows/bulk-delete`, {
    method: "POST",
    body: JSON.stringify({ revision, row_ids: rowIds })
  });
}

export function previewImport(draftId: number, revision: number, file: File): Promise<PositionImportPreview> {
  const formData = new FormData();
  formData.append("revision", String(revision));
  formData.append("file", file);
  return api<PositionImportPreview>(`/api/input-drafts/${draftId}/import-preview`, { method: "POST", body: formData });
}

export function applyImport(
  draftId: number,
  revision: number,
  token: string
): Promise<PositionRevisionResponse & { diff: PositionDiff }> {
  return api<PositionRevisionResponse & { diff: PositionDiff }>(`/api/input-drafts/${draftId}/import-apply`, {
    method: "POST",
    body: JSON.stringify({ revision, token })
  });
}

export function validateDraft(draftId: number): Promise<PositionDraftValidation> {
  return api<PositionDraftValidation>(`/api/input-drafts/${draftId}/validate`, { method: "POST" });
}

export function publishDraft(draftId: number, payload: PublishPayload): Promise<PublishResponse> {
  return api<PublishResponse>(`/api/input-drafts/${draftId}/publish`, {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function discardDraft(draftId: number, revision: number): Promise<PositionDraft> {
  return api<PositionDraft>(`/api/input-drafts/${draftId}/discard`, {
    method: "POST",
    body: JSON.stringify({ revision })
  });
}

export function downloadDraft(draftId: number, revision: number): Promise<void> {
  return download(`/api/input-drafts/${draftId}/download`, `position-draft-r${revision}.xlsx`);
}
