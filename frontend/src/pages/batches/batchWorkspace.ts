import type { Batch } from "../../types";

export type BatchWorkflow = "delivery" | "self_operated_inbound";

export const DELIVERY_VERSION_KINDS = [
  { value: "purchase", label: "采购需求" },
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "position", label: "MSKU定位" },
  { value: "template", label: "导出模板" }
];

export const SELF_OPERATED_VERSION_KINDS = [
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "self_operated_inbound", label: "待入库 API 数据" },
  { value: "inbound_template", label: "积加入库模板" }
];

export function canDeleteBatch(batch: Batch): boolean {
  return batch.status !== "queued" && batch.status !== "running";
}
