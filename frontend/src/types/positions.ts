import type { PositionIssue } from "./inputVersions";

type PositionChangeType = "unchanged" | "added" | "modified" | "deleted";

export interface PositionDiff {
  added: number;
  modified: number;
  deleted: number;
  unchanged: number;
}

export interface PositionDraft {
  id: number;
  kind: "position";
  base_version_id: number;
  base_version_name: string;
  active_version_id: number | null;
  active_version_name: string | null;
  status: "editing" | "published" | "discarded";
  revision: number;
  created_by: number;
  updated_by: number;
  created_at: string;
  updated_at: string;
  row_count: number;
  modified_count: number;
  diff: PositionDiff;
  issues: PositionIssue[];
  error_count: number;
  warning_count: number;
  valid: boolean;
}

export interface PositionDraftRow {
  id: number;
  draft_id: number;
  row_order: number;
  store_site: string;
  jiaji_sku: string;
  msku: string;
  scale_position: string;
  stocking_position: string;
  change_type: PositionChangeType;
  deleted: boolean;
  issues: PositionIssue[];
}

export interface PositionDraftRowsPage {
  rows: PositionDraftRow[];
  total: number;
  offset: number;
  limit: number;
}

export interface PositionDraftValidation {
  draft_id: number;
  revision: number;
  diff: PositionDiff;
  issues: PositionIssue[];
  error_count: number;
  warning_count: number;
  valid: boolean;
}

export interface PositionImportPreview extends PositionDraftValidation {
  token: string;
  row_count: number;
}
