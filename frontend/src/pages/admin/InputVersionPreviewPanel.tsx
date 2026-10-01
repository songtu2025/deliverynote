import { useMemo } from "react";
import { Alert, Button, Spin, Table, Typography } from "antd";
import type { TableProps } from "antd";

import type { InputVersion, InputVersionInspection, InputVersionPreviewValue } from "../../types";
import type { InputKind } from "./adminConstants";

interface InputVersionPreviewPanelProps {
  kind: InputKind;
  label: string;
  activeVersion: InputVersion | null;
  inspection: InputVersionInspection | null;
  loading: boolean;
  inspectionLoading: boolean;
  inspectionError: { versionId: number; message: string } | null;
  onRetry: () => void;
}

type PreviewRow = Record<string, InputVersionPreviewValue>;

function formatPreviewValue(value: InputVersionPreviewValue): string | number {
  if (typeof value === "boolean") return value ? "是" : "否";
  return value ?? "—";
}

export function InputVersionPreviewPanel({
  kind,
  label,
  activeVersion,
  inspection,
  loading,
  inspectionLoading,
  inspectionError,
  onRetry
}: InputVersionPreviewPanelProps) {
  const summary = inspection?.summary ?? null;
  const preview = inspection?.preview ?? null;
  const inspectionReady = Boolean(activeVersion && inspection);
  const tableComponents = useMemo<NonNullable<TableProps<PreviewRow>["components"]>>(
    () => ({ table: (props) => <table {...props} aria-label={`${label}数据预览`} /> }),
    [label]
  );
  const columns = useMemo<NonNullable<TableProps<PreviewRow>["columns"]>>(
    () => [
      {
        title: "Excel 行",
        dataIndex: "__excelRow",
        key: "__excelRow",
        width: 84,
        fixed: "left",
        render: (value: InputVersionPreviewValue) => formatPreviewValue(value)
      },
      ...(preview?.columns ?? []).map((column) => ({
        title: column,
        dataIndex: column,
        key: column,
        ellipsis: true,
        width: Math.max(140, Math.min(240, column.length * 18 + 48)),
        render: (value: InputVersionPreviewValue) => formatPreviewValue(value)
      }))
    ],
    [preview]
  );
  const rows = useMemo(
    () =>
      (preview?.rows ?? []).map((row, index) => ({
        ...row,
        __excelRow: (preview?.offset ?? 0) + index + 2,
        __previewKey: String((preview?.offset ?? 0) + index)
      })),
    [preview]
  );

  if (loading) {
    return (
      <div className="input-data-loading">
        <Spin description="读取资料状态" />
      </div>
    );
  }
  if (!activeVersion) {
    return (
      <Alert type="warning" showIcon title={`${label}尚无启用版本`} description="上传并启用通过校验的 Excel 文件。" />
    );
  }
  if (inspectionLoading || (!inspectionReady && !inspectionError)) {
    return (
      <div className="input-data-loading">
        <Spin description="读取摘要与预览" />
      </div>
    );
  }
  if (inspectionError?.versionId === activeVersion.id) {
    return (
      <Alert
        type="error"
        showIcon
        title="无法读取当前版本内容"
        description={inspectionError.message}
        action={
          <Button size="small" onClick={onRetry}>
            重新加载
          </Button>
        }
      />
    );
  }
  if (!inspectionReady || !summary || !preview) return null;

  const metricItems =
    kind === "position"
      ? [
          `${summary.metrics.sites ?? 0} 个站点`,
          `${summary.metrics.skus ?? 0} 个积加 SKU`,
          `${summary.metrics.mskus ?? 0} 个 MSKU`
        ]
      : kind === "supplier"
        ? [
            `${summary.metrics.aliases ?? 0} 个别名`,
            `${summary.metrics.suppliers_with_aliases ?? 0} 个供应商已配置别名`
          ]
        : [];

  return (
    <>
      <div className="input-data-preview-heading">
        <div>
          <Typography.Title level={5}>数据预览</Typography.Title>
          <Typography.Text type="secondary">预览不会修改原文件。</Typography.Text>
        </div>
        <Typography.Text className="input-data-preview-summary" type="secondary">
          <span>
            当前展示前 {preview.rows.length} 行，共 {preview.total} 行 · {summary.columns.length} 个字段
          </span>
          {metricItems.map((item) => (
            <span className="input-data-preview-metric" key={item}>
              {item}
            </span>
          ))}
        </Typography.Text>
      </div>
      <Table<PreviewRow>
        className="input-data-preview-table"
        rowKey="__previewKey"
        size="small"
        columns={columns}
        dataSource={rows}
        components={tableComponents}
        pagination={false}
        scroll={{ x: "max-content" }}
        locale={{ emptyText: "当前版本没有可预览的数据" }}
      />
    </>
  );
}
