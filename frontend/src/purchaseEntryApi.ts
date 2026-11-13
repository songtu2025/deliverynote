import { api, download } from "./api";

type ExcelNumber = number | string;

interface PurchaseEntryBatch {
  order_number: string;
  source_site: string;
  delivery_date: string;
  row_count: number;
  total_quantity: ExcelNumber;
}

export interface PurchaseEntryPreview {
  supplier_code: string;
  order_prefix: string;
  row_count: number;
  batch_count: number;
  total_quantity: ExcelNumber;
  skipped_zero_count: number;
  batches: PurchaseEntryBatch[];
  preview: Array<{
    order_number: string;
    sku: string;
    site: string;
    msku: string;
    warehouse: string;
    quantity: ExcelNumber;
    unit_price: ExcelNumber;
    delivery_date: string;
    note: string;
  }>;
  versions: { supplier: number; product: number; sku_warehouse: number; purchase_template: number };
}

export type PurchaseExportMode = "merged" | "split";

export function previewPurchaseEntry(file: File): Promise<PurchaseEntryPreview> {
  const body = new FormData();
  body.append("file", file);
  return api("/api/purchase-entry/preview", { method: "POST", body });
}

export function exportPurchaseEntry(
  file: File,
  mode: PurchaseExportMode,
  versions: PurchaseEntryPreview["versions"]
): Promise<void> {
  const body = new FormData();
  body.append("file", file);
  body.append("mode", mode);
  body.append("version_ids", JSON.stringify(versions));
  return download("/api/purchase-entry/export", mode === "merged" ? "采购单录入.xlsx" : "采购单分批.zip", {
    method: "POST",
    body
  });
}
