import type { InputVersion } from "./inputVersions";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "./rules";

interface ReceiptTotals {
  cumulative_total?: number;
  history_total?: number | null;
  requested_total?: number | null;
  issue_count?: number;
  captured_at?: string;
  source?: "api" | "upload";
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
  receipt?: ReceiptTotals | null;
}

export interface Batch {
  manual_allowances?: {
    supplier_code: string;
    supplier_name: string;
    sku: string;
    full_site: string;
    quantity: number;
    reason: string;
  }[];
  manual_allowance_disabled_reason?: string | null;
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
  transfer_sources?: {
    batch_id: number;
    batch_name: string;
    record_count: number;
    quantity: number;
    file_ids: number[];
  }[];
  versions?: Record<string, InputVersion>;
  jobs?: Partial<Record<"compute" | "export" | "prepare" | "purchase_snapshot", Job>>;
  receipt?: ReceiptTotals | null;
  summary?: {
    delivery_total: number;
    import_total: number;
    manual_total: number;
    conserved: boolean;
  };
}

export interface DeliveryImportRow {
  file_id: number;
  file_name: string;
  row_index: number;
  warehouse: string;
  supplier_code: string;
  sku: string;
  quantity: number;
  site: string;
  document_note: string;
  delivery_note: string;
}

export interface InboundImportRow {
  file_id: number;
  file_name: string;
  row_index: number;
  warehouse: string;
  sku: string;
  quantity: number;
  site: string;
  inbound_no: string;
  po_code: string;
  delivery_no: string;
  overreceipt_reason: string | null;
}

export interface Job {
  id: number;
  batch_id: number;
  kind: "compute" | "export" | "prepare" | "purchase_snapshot";
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

type ExceptionReasonCode =
  | "product_not_found"
  | "ambiguous_product_site"
  | "purchase_balance_exceeded"
  | "purchase_not_found"
  | "overreceipt_limit_exceeded"
  | "inbound_order_not_found"
  | "supplier_mismatch"
  | "po_name_missing"
  | "receivable_invalid"
  | "receivable_exceeded"
  | "unknown";

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
  transferred_quantity?: number;
  offline_quantity?: number;
  offline_note?: string;
  transfers?: { target_batch_id: number; quantity: number; full_site: string }[];
  reason: string;
  reason_code: ExceptionReasonCode;
  allowed_actions: "split"[];
  status: string;
  scale_position: string | number;
  stocking_position: string | number;
  parts: SplitPart[];
}
