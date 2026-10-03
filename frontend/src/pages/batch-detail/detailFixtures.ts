import type { Batch, BatchFile, InputVersion, DeliveryException, Job } from "../../types";
export type DetailBatchFixture = Batch & {
  files: BatchFile[];
  versions: Record<string, InputVersion>;
  jobs: Partial<Record<"compute" | "export", Job>>;
};
export const fixtureVersion = (id: number, kind: string) => ({
  id,
  kind,
  name: `${kind}-v1`,
  original_name: `${kind}.xlsx`,
  active: true,
  created_by: 1,
  created_at: "2026-07-21T08:00:00"
});

export function createDetailBatch(): DetailBatchFixture {
  return {
    id: 7,
    name: "2026-07-21 交货批次",
    status: "succeeded",
    created_by: 1,
    version_ids: { purchase: 1, product: 2, supplier: 3, position: 4, template: 5 },
    overreceipt_rule: {
      id: 9,
      name: "短尾超收 V1",
      short_tail_limit: 50,
      medium_tail_limit: 20,
      long_tail_limit: 10,
      allowed_warehouses: ["水鞋-广州仓"],
      active: false,
      created_by: 1,
      created_at: "2026-07-21T07:00:00"
    },
    versions: {
      purchase: fixtureVersion(1, "purchase"),
      product: fixtureVersion(2, "product"),
      supplier: fixtureVersion(3, "supplier"),
      position: fixtureVersion(4, "position"),
      template: fixtureVersion(5, "template")
    },
    jobs: {},
    error_message: null,
    download_ready: false,
    merged_download_ready: false,
    created_at: "2026-07-21T08:00:00",
    updated_at: "2026-07-21T09:00:00",
    file_count: 2,
    summary: { delivery_total: 160, import_total: 100, manual_total: 60, conserved: true },
    files: [
      {
        id: 10,
        batch_id: 7,
        original_name: "KuangBiao-A交货单.xlsx",
        file_order: 1,
        supplier_name: "KuangBiao",
        supplier_code: "GYS-023",
        document_note: "A",
        delivery_total: 80,
        import_total: 80,
        manual_total: 0,
        download_ready: false
      },
      {
        id: 11,
        batch_id: 7,
        original_name: "KuangBiao-B交货单.xlsx",
        file_order: 2,
        supplier_name: "KuangBiao",
        supplier_code: "GYS-023",
        document_note: "B",
        delivery_total: 80,
        import_total: 20,
        manual_total: 60,
        download_ready: false
      }
    ]
  };
}
export function createDetailExceptions(): DeliveryException[] {
  return [
    {
      id: 30,
      batch_file_id: 11,
      sku: "SKU-A",
      original_site: "US",
      full_site: "AMAZON:SEEKWAY:US",
      destination: "水鞋-东莞仓",
      delivery_quantity: 80,
      allocated_quantity: 20,
      purchase_allocated_quantity: 20,
      overreceipt_allocated_quantity: 0,
      overreceipt_remaining_quantity: null,
      manual_quantity: 60,
      reason: "超出采购未交量",
      reason_code: "purchase_balance_exceeded",
      allowed_actions: ["split"],
      status: "pending",
      scale_position: "短尾",
      stocking_position: "备货",
      parts: []
    },
    {
      id: 31,
      batch_file_id: 11,
      sku: "SKU-B",
      original_site: "CA",
      full_site: "AMAZON:SEEKWAY:CA",
      destination: "水鞋-东莞仓",
      delivery_quantity: 20,
      allocated_quantity: 0,
      purchase_allocated_quantity: 0,
      overreceipt_allocated_quantity: 0,
      overreceipt_remaining_quantity: null,
      manual_quantity: 20,
      reason: "未找到可交货采购需求",
      reason_code: "purchase_not_found",
      allowed_actions: ["split"],
      status: "pending",
      scale_position: "中尾",
      stocking_position: "不备货",
      parts: []
    },
    {
      id: 32,
      batch_file_id: 11,
      sku: "SKU-C",
      original_site: "US",
      full_site: "AMAZON:OTHER:US、AMAZON:SEEKWAY:US",
      destination: "",
      delivery_quantity: 12,
      allocated_quantity: 0,
      purchase_allocated_quantity: 0,
      overreceipt_allocated_quantity: 0,
      overreceipt_remaining_quantity: null,
      manual_quantity: 12,
      reason: "产品信息站点不唯一",
      reason_code: "ambiguous_product_site",
      allowed_actions: ["split"],
      status: "pending",
      scale_position: "",
      stocking_position: "",
      parts: []
    },
    {
      id: 33,
      batch_file_id: 11,
      sku: "SKU-D",
      original_site: "US",
      full_site: "AMAZON:SEEKWAY:US",
      destination: "水鞋-广州仓",
      delivery_quantity: 85,
      allocated_quantity: 70,
      purchase_allocated_quantity: 20,
      overreceipt_allocated_quantity: 50,
      overreceipt_remaining_quantity: 0,
      manual_quantity: 15,
      reason: "超出允许超收量",
      reason_code: "overreceipt_limit_exceeded",
      allowed_actions: ["split"],
      status: "pending",
      scale_position: "短尾",
      stocking_position: "备货",
      parts: []
    }
  ];
}
export function fixtureJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 88,
    batch_id: 7,
    kind: "compute",
    status: "running",
    attempts: 1,
    error_message: null,
    download_ready: false,
    created_at: "2026-07-21T09:00:00",
    claimed_at: null,
    heartbeat_at: null,
    finished_at: null,
    ...overrides
  };
}
