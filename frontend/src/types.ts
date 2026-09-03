export type Role = "admin" | "operator";

export interface User {
  id: number;
  username: string;
  role: Role;
  active: boolean;
}

export interface BatchFile {
  id: number;
  batch_id: number;
  original_name: string;
  file_order: number;
  supplier_name: string;
  supplier_code: string;
  document_note: string;
  delivery_total: number;
  import_total: number;
  manual_total: number;
  download_ready: boolean;
}

export interface Batch {
  id: number;
  name: string;
  status: string;
  workflow?: "delivery" | "self_operated_inbound";
  created_by: number;
  version_ids: Record<string, number>;
  overreceipt_rule?: OverreceiptRuleVersion | null;
  self_operated_overreceipt_rule?: SelfOperatedOverreceiptRuleVersion | null;
  inbound_file?: {
    original_name: string;
    uploaded: boolean;
  } | null;
  error_message: string | null;
  download_ready: boolean;
  merged_download_ready: boolean;
  created_at: string;
  updated_at: string;
  file_count: number;
  files?: BatchFile[];
  versions?: Record<string, InputVersion>;
  jobs?: Partial<Record<"compute" | "export", Job>>;
  site_resolutions?: SelfOperatedSiteResolution[];
  summary?: {
    delivery_total: number;
    import_total: number;
    manual_total: number;
    conserved: boolean;
  };
}

export interface SelfOperatedSiteResolution {
  id: number;
  sku: string;
  original_site: string;
  full_site: string;
  updated_at: string;
}

export interface OverreceiptRuleVersion {
  id: number;
  name: string;
  short_tail_limit: number;
  medium_tail_limit: number;
  long_tail_limit: number;
  allowed_warehouses: string[];
  active: boolean;
  created_by: number;
  created_at: string;
}

export interface SelfOperatedOverreceiptRuleVersion {
  id: number;
  name: string;
  allowance: number;
  active: boolean;
  created_by: number;
  created_at: string;
}

export interface Job {
  id: number;
  batch_id: number;
  kind: "compute" | "export";
  status: string;
  attempts: number;
  error_message: string | null;
  download_ready: boolean;
  created_at: string;
  claimed_at: string | null;
  heartbeat_at: string | null;
  finished_at: string | null;
}

export interface SplitPart {
  id?: number;
  quantity: number;
  destination: string;
  site: string;
  supplier_code: string;
  sku: string;
  delivery_note: string;
  resolved: boolean;
}

export interface DeliveryException {
  id: number;
  batch_file_id: number;
  sku: string;
  original_site: string;
  full_site: string;
  destination: string;
  delivery_quantity: number;
  allocated_quantity: number;
  purchase_allocated_quantity: number | null;
  overreceipt_allocated_quantity: number | null;
  overreceipt_remaining_quantity: number | null;
  manual_quantity: number;
  reason: string;
  status: string;
  scale_position: string | number;
  stocking_position: string | number;
  ordered_days: string | number;
  parts: SplitPart[];
}

export interface InputVersion {
  id: number;
  kind: string;
  name: string;
  original_name: string;
  active: boolean;
  created_by: number;
  created_at: string;
}

export interface PurchaseSyncJob {
  id: number;
  status: "queued" | "running" | "succeeded" | "blocked" | "failed";
  base_version_id: number | null;
  product_version_id: number | null;
  supplier_version_id: number | null;
  candidate_version_id: number | null;
  total_orders: number;
  processed_orders: number;
  raw_detail_count: number;
  eligible_detail_count: number;
  filtered_detail_count: number;
  current_order: string | null;
  issue_count: number;
  warning_count: number;
  diff: Record<string, number>;
  error_message: string | null;
  created_at: string;
  claimed_at: string | null;
  heartbeat_at: string | null;
  finished_at: string | null;
}

export interface PurchaseSyncStatus {
  configured: boolean;
  job: PurchaseSyncJob | null;
}

export interface PurchaseSyncIssue {
  severity: "error" | "warning";
  message: string;
  po_code: string;
  sku: string;
  source_site: string;
  supplier_code: string;
  supplier_name: string;
  warehouse?: string;
  quantity?: number;
  code: string;
}

export interface PurchaseSyncPreview {
  columns: string[];
  rows: Record<string, string | number | null>[];
  total: number;
}

export interface SelfOperatedInboundSyncJob {
  id: number;
  status: "queued" | "running" | "succeeded" | "blocked" | "failed";
  base_version_id: number | null;
  candidate_version_id: number | null;
  total_orders: number;
  raw_detail_count: number;
  eligible_detail_count: number;
  filtered_detail_count: number;
  issue_count: number;
  warning_count: number;
  diff: Record<string, number>;
  error_message: string | null;
  created_at: string;
  claimed_at: string | null;
  heartbeat_at: string | null;
  finished_at: string | null;
}

export interface SelfOperatedInboundSyncStatus {
  configured: boolean;
  active_version: InputVersion | null;
  job: SelfOperatedInboundSyncJob | null;
}

export interface SelfOperatedInboundSyncIssue {
  severity: "error" | "warning";
  message: string;
  order_no: string;
  sku: string;
  source_site: string;
  supplier_code: string;
  supplier_name: string;
  warehouse?: string;
  remaining_quantity?: number;
  purchase_code?: string;
  related_code?: string;
  code: string;
}

export interface SelfOperatedInboundSyncPreview {
  columns: string[];
  rows: Array<Record<string, string | number | null> & { _row_number: number }>;
  total: number;
}

export interface PositionIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  row_numbers: number[];
  before?: number;
  after?: number;
}

export interface InputVersionSummary {
  kind: string;
  row_count: number;
  columns: string[];
  metrics: Record<string, number>;
  issues: PositionIssue[];
}

export type InputVersionPreviewValue = string | number | boolean | null;

export interface InputVersionPreview {
  kind: string;
  columns: string[];
  rows: Record<string, InputVersionPreviewValue>[];
  total: number;
  offset: number;
  limit: number;
}

export interface InputVersionInspection {
  summary: InputVersionSummary;
  preview: InputVersionPreview;
}

export type PositionChangeType = "unchanged" | "added" | "modified" | "deleted";

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
  ordered_days: string;
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

export interface AuditLog {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
  created_at: string;
}
