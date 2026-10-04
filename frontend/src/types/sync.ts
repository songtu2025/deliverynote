import type { InputVersion } from "./inputVersions";

interface PurchaseSyncJob {
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

interface SelfOperatedInboundSyncJob {
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
