import type { InputVersion } from "./inputVersions";
import type { OverreceiptRuleVersion, SelfOperatedOverreceiptRuleVersion } from "./rules";

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

interface SelfOperatedSiteResolution {
  id: number;
  sku: string;
  original_site: string;
  full_site: string;
  updated_at: string;
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
  reason: string;
  reason_code: ExceptionReasonCode;
  allowed_actions: ("split" | "resolve_site")[];
  status: string;
  scale_position: string | number;
  stocking_position: string | number;
  parts: SplitPart[];
}
