import { Tag } from "antd";
import type { TableProps } from "antd";
import type { PurchaseSyncIssue, PurchaseSyncPreview } from "../../types";

type PurchasePreviewRow = PurchaseSyncPreview["rows"][number];

export const purchasePreviewColumns: NonNullable<TableProps<PurchasePreviewRow>["columns"]> = [
  { title: "单据状态", dataIndex: "单据状态", width: 90 },
  { title: "供应商", dataIndex: "供应商", width: 140, ellipsis: true },
  { title: "SKU", dataIndex: "SKU", width: 160, ellipsis: true },
  {
    title: "平台站点",
    dataIndex: "平台站点",
    width: 200,
    ellipsis: true,
    render: (value: string | null) => (value === "共享" ? <Tag color="warning">共享 · 不可自动匹配</Tag> : value || "—")
  },
  { title: "目的仓", dataIndex: "目的仓", width: 150, ellipsis: true },
  { title: "未交量", dataIndex: "未交量", width: 90, align: "right" }
];

export const purchaseIssueColumns: NonNullable<TableProps<PurchaseSyncIssue>["columns"]> = [
  {
    title: "级别",
    dataIndex: "severity",
    width: 88,
    render: (severity: PurchaseSyncIssue["severity"]) => (
      <Tag color={severity === "error" ? "error" : "warning"}>{severity === "error" ? "错误" : "提醒"}</Tag>
    )
  },
  { title: "问题", dataIndex: "message", width: 260 },
  { title: "采购单号", dataIndex: "po_code", width: 128 },
  { title: "SKU", dataIndex: "sku", width: 150 },
  {
    title: "目的仓",
    dataIndex: "warehouse",
    width: 150,
    render: (value: string | undefined) => value || "—"
  },
  {
    title: "未交量",
    dataIndex: "quantity",
    width: 100,
    align: "right",
    render: (value: number | undefined) => value ?? "—"
  },
  { title: "接口站点", dataIndex: "source_site", width: 160 },
  { title: "供应商编号", dataIndex: "supplier_code", width: 145 },
  { title: "供应商名称", dataIndex: "supplier_name", width: 170 },
  { title: "问题类型", dataIndex: "code", width: 140 }
];
