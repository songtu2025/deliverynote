import { Alert, Button, Drawer, Space, Table, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { TableProps } from "antd";
import type { SyncInspectionState, SyncIssueFilter } from "./useSyncInspection";

type PreviewConfig<Row> = {
  title: string;
  width: number;
  columns: TableProps<Row>["columns"];
  scroll: TableProps<Row>["scroll"];
};
type IssuesConfig<Issue> = {
  title: string;
  width: number;
  columns: TableProps<Issue>["columns"];
  rowKey: TableProps<Issue>["rowKey"];
};
export default function SyncInspectionDrawers<
  Row extends Record<string, unknown>,
  Issue extends { severity: "warning" | "error" }
>({
  inspection,
  previewConfig,
  issuesConfig,
  onDownload
}: {
  inspection: SyncInspectionState<{ rows: Row[]; total: number }, Issue>;
  previewConfig: PreviewConfig<Row>;
  issuesConfig: IssuesConfig<Issue>;
  onDownload: () => Promise<void>;
}) {
  const {
    preview,
    previewOpen,
    previewLoading,
    previewError,
    setPreviewOpen,
    issues,
    issuesOpen,
    issuesLoading,
    issuesError,
    setIssuesOpen,
    issueFilter,
    setIssueFilter
  } = inspection;
  const filteredIssues = issues.filter((issue) => issueFilter === "all" || issue.severity === issueFilter);
  return (
    <>
      <Drawer
        rootClassName="purchase-sync-issues-drawer"
        title={previewConfig.title}
        size={previewConfig.width}
        open={previewOpen}
        destroyOnHidden
        onClose={() => setPreviewOpen(false)}
      >
        {previewError ? (
          <Alert type="error" showIcon title="无法读取候选数据" description={previewError} />
        ) : (
          <>
            <Typography.Paragraph type="secondary">
              共 {preview?.total ?? 0} 行，当前展示前 {Math.min(preview?.total ?? 0, 100)} 行。
            </Typography.Paragraph>
            <Table<Row>
              size="small"
              loading={previewLoading}
              columns={previewConfig.columns}
              dataSource={preview?.rows ?? []}
              rowKey={(row) => String(row._row_number)}
              pagination={false}
              scroll={previewConfig.scroll}
              locale={{ emptyText: "当前候选版本没有可预览数据" }}
            />
          </>
        )}
      </Drawer>

      <Drawer
        rootClassName="purchase-sync-issues-drawer"
        title={issuesConfig.title}
        size={issuesConfig.width}
        open={issuesOpen}
        destroyOnHidden
        extra={
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void onDownload()}>
            下载完整清单
          </Button>
        }
        onClose={() => setIssuesOpen(false)}
      >
        <div className="purchase-sync-issues-toolbar">
          <Typography.Text type="secondary">
            共 {issues.length} 条，显示 {filteredIssues.length} 条。
          </Typography.Text>
          <Space size={6} wrap>
            <Typography.Text type="secondary">筛选：</Typography.Text>
            {(
              [
                ["warning", "共享站点提醒"],
                ["error", "映射错误"],
                ["all", "全部"]
              ] as Array<[SyncIssueFilter, string]>
            ).map(([value, label]) => (
              <Button
                key={value}
                size="small"
                type={issueFilter === value ? "primary" : "default"}
                onClick={() => setIssueFilter(value)}
              >
                {label}
              </Button>
            ))}
          </Space>
        </div>
        {issuesError ? (
          <Alert type="error" showIcon title="无法读取异常数据" description={issuesError} />
        ) : (
          <Table<Issue>
            className="purchase-sync-issues-table"
            rowKey={issuesConfig.rowKey}
            size="small"
            loading={issuesLoading}
            columns={issuesConfig.columns}
            dataSource={filteredIssues}
            pagination={filteredIssues.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
            scroll={{ x: "max-content" }}
            locale={{ emptyText: "当前筛选条件下没有异常数据" }}
          />
        )}
      </Drawer>
    </>
  );
}
