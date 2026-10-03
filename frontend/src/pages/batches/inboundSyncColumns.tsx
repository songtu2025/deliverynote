import { Tag } from "antd";
import type { TableProps } from "antd";
import type { SelfOperatedInboundSyncIssue, SelfOperatedInboundSyncPreview } from "../../types";

export const inboundIssueColumns: NonNullable<TableProps<SelfOperatedInboundSyncIssue>["columns"]> = [
  {
    title: "级别",
    dataIndex: "severity",
    width: 80,
    render: (value: SelfOperatedInboundSyncIssue["severity"]) => (
      <Tag color={value === "error" ? "error" : "warning"}>{value === "error" ? "错误" : "提醒"}</Tag>
    )
  },
  { title: "问题", dataIndex: "message", width: 250 },
  { title: "入库单号", dataIndex: "order_no", width: 150 },
  { title: "SKU", dataIndex: "sku", width: 170 },
  {
    title: "入库仓",
    dataIndex: "warehouse",
    width: 150,
    render: (value: string | undefined) => value || "—"
  },
  {
    title: "剩余应收货",
    dataIndex: "remaining_quantity",
    width: 110,
    align: "right",
    render: (value: number | undefined) => value ?? "—"
  },
  { title: "关联采购单", dataIndex: "purchase_code", width: 145, render: (value) => value || "—" },
  { title: "关联交货单/调拨单", dataIndex: "related_code", width: 180, render: (value) => value || "—" },
  { title: "接口站点", dataIndex: "source_site", width: 155 },
  { title: "供应商编号", dataIndex: "supplier_code", width: 135, render: (value) => value || "—" },
  { title: "供应商名称", dataIndex: "supplier_name", width: 150, render: (value) => value || "—" },
  { title: "问题类型", dataIndex: "code", width: 145 }
];

export function inboundPreviewColumns(preview: SelfOperatedInboundSyncPreview | null) {
  const previewColumnWidths: Record<string, number> = {
    入库单号: 160,
    入库仓: 150,
    SKU: 190,
    平台站点: 230,
    "关联交货单/调拨单": 180,
    关联采购单: 160,
    应收货: 100
  };
  return Object.keys(previewColumnWidths)
    .filter((column) => preview?.columns.includes(column))
    .map((column) => ({
      title: column === "应收货" ? "剩余应收货" : column,
      dataIndex: column,
      key: column,
      width: previewColumnWidths[column],
      ellipsis: true,
      render: (value: string | number | null) =>
        column === "平台站点" && value === "共享" ? <Tag color="warning">共享 · 不可自动匹配</Tag> : (value ?? "—")
    }));
}
