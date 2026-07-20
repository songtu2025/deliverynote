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
  created_by: number;
  version_ids: Record<string, number>;
  error_message: string | null;
  download_ready: boolean;
  created_at: string;
  updated_at: string;
  files?: BatchFile[];
  summary?: {
    delivery_total: number;
    import_total: number;
    manual_total: number;
    conserved: boolean;
  };
}

export interface Job {
  id: number;
  batch_id: number;
  kind: "compute" | "export";
  status: string;
  attempts: number;
  error_message: string | null;
  download_ready: boolean;
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
  manual_quantity: number;
  reason: string;
  status: string;
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