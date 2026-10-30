import { api } from "./api";

export type PurchaseOption = {
  id: string;
  po_code: string;
  site: string;
  warehouse: string;
  remaining_quantity: number;
};

export type InboundAllocation = {
  id: string;
  po_code: string | null;
  delivery_no: string | null;
  inbound_no: string | null;
  site: string | null;
  warehouse: string | null;
  history_quantity: number | null;
  normal_quantity: number | null;
  overreceipt_quantity: number | null;
  current_quantity: number | null;
};

export type PurchaseOptions = { items: PurchaseOption[]; queried_at: string };
export type InboundAllocations = {
  items: InboundAllocation[];
  batch_updated_at: string;
  history_captured_at: string | null;
};

export const getPurchaseOptions = (exceptionId: number) =>
  api<PurchaseOptions>(`/api/exceptions/${exceptionId}/purchase-options`);

export const getInboundAllocations = (exceptionId: number) =>
  api<InboundAllocations>(`/api/exceptions/${exceptionId}/inbound-allocation`);
