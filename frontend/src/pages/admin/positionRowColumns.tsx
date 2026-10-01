import { Button, Popconfirm, Space, Tag, Typography } from "antd";
import type { TableProps } from "antd";

import type { PositionDraftRow, PositionIssue } from "../../types";

interface PositionRowColumnOptions {
  disabled: boolean;
  copying: boolean;
  deleting: boolean;
  deleteConfirmRowId: number | null;
  onEdit: (row: PositionDraftRow) => void;
  onCopy: (row: PositionDraftRow) => Promise<void>;
  onDeleteOpenChange: (row: PositionDraftRow, open: boolean) => void;
  onDeleteConfirm: (row: PositionDraftRow) => Promise<void>;
}

function rowActionLabel(action: string, row: PositionDraftRow): string {
  return `${action} ${row.store_site} / ${row.jiaji_sku} / ${row.msku || "无 MSKU"}`;
}

export function createPositionRowColumns({
  disabled,
  copying,
  deleting,
  deleteConfirmRowId,
  onEdit,
  onCopy,
  onDeleteOpenChange,
  onDeleteConfirm
}: PositionRowColumnOptions): NonNullable<TableProps<PositionDraftRow>["columns"]> {
  return [
    { title: "店铺-站点", dataIndex: "store_site", width: 130, ellipsis: true },
    { title: "积加 SKU", dataIndex: "jiaji_sku", width: 120, ellipsis: true },
    { title: "MSKU", dataIndex: "msku", width: 120, ellipsis: true, render: (value: string) => value || "—" },
    {
      title: "规模定位",
      dataIndex: "scale_position",
      width: 90,
      ellipsis: true,
      render: (value: string) => value || "—"
    },
    {
      title: "备货定位",
      dataIndex: "stocking_position",
      width: 100,
      ellipsis: true,
      render: (value: string) => value || "—"
    },
    {
      title: "修改状态",
      dataIndex: "change_type",
      width: 90,
      render: (value: PositionDraftRow["change_type"]) => {
        const definitions = {
          unchanged: { color: "default", label: "未变化" },
          added: { color: "green", label: "新增" },
          modified: { color: "blue", label: "已修改" },
          deleted: { color: "red", label: "已删除" }
        } as const;
        const definition = definitions[value];
        return <Tag color={definition.color}>{definition.label}</Tag>;
      }
    },
    {
      title: "问题",
      dataIndex: "issues",
      width: 80,
      render: (issues: PositionIssue[]) =>
        issues.length === 0 ? (
          <Typography.Text type="secondary">无</Typography.Text>
        ) : (
          <Tag color={issues.some((issue) => issue.severity === "error") ? "error" : "warning"}>{issues.length} 项</Tag>
        )
    },
    {
      title: "操作",
      key: "actions",
      width: 150,
      render: (_, row) => (
        <Space size={0}>
          <Button
            className="position-record-action"
            size="small"
            type="link"
            aria-label={rowActionLabel("编辑", row)}
            disabled={disabled}
            onClick={() => onEdit(row)}
          >
            编辑
          </Button>
          <Button
            className="position-record-action"
            size="small"
            type="link"
            aria-label={rowActionLabel("复制", row)}
            disabled={disabled}
            loading={copying}
            onClick={() => void onCopy(row)}
          >
            复制
          </Button>
          <Popconfirm
            fresh
            open={deleteConfirmRowId === row.id}
            title={`删除 ${row.jiaji_sku}？`}
            description="删除会立即保存到服务器草稿，发布前不会影响正式版本。"
            okText="确认删除"
            cancelText="取消"
            cancelButtonProps={{ disabled: deleting && deleteConfirmRowId === row.id }}
            onOpenChange={(open) => onDeleteOpenChange(row, open)}
            onConfirm={() => onDeleteConfirm(row)}
          >
            <Button
              className="position-record-action"
              size="small"
              type="link"
              danger
              aria-label={rowActionLabel("删除", row)}
              disabled={disabled}
              loading={deleting}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      )
    }
  ];
}
