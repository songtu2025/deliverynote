import { useState } from "react";
import { Alert, Button, Popconfirm, Space, Tag, Typography } from "antd";
import { CheckCircleFilled, EyeOutlined, SyncOutlined } from "@ant-design/icons";
import { formatBeijingDateTime } from "../../dateTime";
import { getInboundSyncPreview, getInboundSyncIssues } from "../../syncApi";
import { useSyncInspection } from "./useSyncInspection";
import type { useInboundSync } from "./useInboundSync";
import type { SelfOperatedInboundSyncStatus } from "../../types";
import SyncInspectionDrawers from "./SyncInspectionDrawers";
import { inboundIssueColumns, inboundPreviewColumns } from "./inboundSyncColumns";

export default function InboundSyncPanel({
  syncStatus,
  sync
}: {
  syncStatus: SelfOperatedInboundSyncStatus | null;
  sync: ReturnType<typeof useInboundSync>;
}) {
  const {
    syncStarting,
    syncActivating,
    syncError,
    syncJob,
    syncRunning,
    syncCandidateActive,
    startInboundSync,
    activateInboundSync,
    downloadInboundIssues
  } = sync;
  const [syncDetailsOpen, setSyncDetailsOpen] = useState(false);
  const inspection = useSyncInspection({
    jobId: syncJob?.id,
    hasCandidate: Boolean(syncJob?.candidate_version_id),
    readPreview: getInboundSyncPreview,
    readIssues: getInboundSyncIssues,
    clearIssuesOnOpen: true
  });
  const { openPreview: openInboundPreview, openIssues: openInboundIssues } = inspection;
  return (
    <>
      <section className="purchase-sync-card self-operated-sync-card" aria-label="积加待入库数据同步">
        <div className="purchase-sync-heading">
          <div>
            <Space size={8} wrap>
              <Typography.Title level={5}>积加待入库数据</Typography.Title>
              <Tag color="processing">待入库 + 部分入库</Tag>
            </Space>
            <Typography.Text type="secondary">同步待入库和部分入库采购单；启用后用于新批次。</Typography.Text>
          </div>
          <Button
            type="primary"
            icon={<SyncOutlined />}
            loading={syncStarting}
            disabled={!syncStatus?.configured || syncRunning}
            onClick={() => void startInboundSync()}
          >
            {syncRunning ? "正在同步" : "同步待入库数据"}
          </Button>
        </div>

        {!syncStatus?.configured && <Alert type="warning" showIcon title="积加 API 尚未完成配置" />}
        {syncError && <Alert type="error" showIcon title="同步操作失败" description={syncError} />}
        {syncRunning && syncJob && (
          <div className="purchase-sync-progress" aria-label="待入库同步进度">
            <div>
              <strong>{syncJob.status === "queued" ? "等待后台任务" : "正在读取待入库单"}</strong>
              <span>{syncJob.total_orders ? `已读取 ${syncJob.total_orders} 张入库单` : "正在读取数据"}</span>
            </div>
            <div
              className="purchase-sync-progress-track is-indeterminate"
              role="progressbar"
              aria-label="正在同步待入库数据"
            >
              <span />
            </div>
          </div>
        )}
        {syncJob?.status === "failed" && (
          <Alert type="error" showIcon title="本次同步失败" description={syncJob.error_message ?? "请稍后重试"} />
        )}
        {syncJob?.status === "blocked" && (
          <Alert
            type="warning"
            showIcon
            title={`发现 ${syncJob.issue_count} 条阻断问题，未生成候选版本`}
            description="核对入库单号、SKU、入库仓、关联单号和站点；本环节不校验供应商。"
            action={
              <Space size={4} wrap>
                <Button size="small" icon={<EyeOutlined />} onClick={() => void openInboundIssues("error")}>
                  查看异常数据
                </Button>
                <Button size="small" onClick={() => void downloadInboundIssues()}>
                  下载问题清单
                </Button>
              </Space>
            }
          />
        )}
        {syncJob?.status === "succeeded" && (
          <div
            className={`purchase-sync-result${syncCandidateActive ? " is-active" : ""}${syncDetailsOpen ? "" : " is-collapsed"}`}
          >
            <div className="purchase-sync-result-copy">
              <CheckCircleFilled />
              <div>
                <strong>{syncCandidateActive ? "数据已启用" : "同步完成，待启用"}</strong>
                <Typography.Text type="secondary">
                  {syncDetailsOpen
                    ? `接口明细 ${syncJob.raw_detail_count} 行，保留 ${syncJob.eligible_detail_count} 行，过滤已全部入库 ${syncJob.filtered_detail_count} 行`
                    : `保留 ${syncJob.eligible_detail_count} 行 · ${formatBeijingDateTime(syncJob.finished_at ?? syncJob.created_at)}`}
                </Typography.Text>
              </div>
            </div>
            {syncDetailsOpen && (
              <dl className="purchase-sync-diff">
                <div>
                  <dt>新增匹配项</dt>
                  <dd>{syncJob.diff.added_lines ?? 0}</dd>
                </div>
                <div>
                  <dt>数量变化项</dt>
                  <dd>{syncJob.diff.changed_lines ?? 0}</dd>
                </div>
                <div>
                  <dt>移除匹配项</dt>
                  <dd>{syncJob.diff.removed_lines ?? 0}</dd>
                </div>
                <div>
                  <dt>候选剩余应收总量</dt>
                  <dd>{syncJob.diff.after_quantity ?? 0}</dd>
                </div>
              </dl>
            )}
            {syncDetailsOpen && syncJob.warning_count > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`包含 ${syncJob.warning_count} 条“共享”站点数据`}
                description="数据保留原值，但不能自动匹配，需业务复核。"
                action={
                  <Space size={4} wrap>
                    <Button size="small" onClick={() => void openInboundIssues("warning")}>
                      查看异常数据
                    </Button>
                    <Button size="small" onClick={() => void downloadInboundIssues()}>
                      下载提醒清单
                    </Button>
                  </Space>
                }
              />
            )}
            <Space className="purchase-sync-actions" size={8} wrap>
              <Button type="link" onClick={() => setSyncDetailsOpen((value) => !value)}>
                {syncDetailsOpen ? "收起同步详情" : "查看同步详情"}
              </Button>
              {syncDetailsOpen && (
                <Button icon={<EyeOutlined />} onClick={() => void openInboundPreview()}>
                  预览候选数据
                </Button>
              )}
              {!syncCandidateActive && (
                <Popconfirm
                  title="启用最新待入库数据？"
                  description="仅用于新批次；已有批次不变。"
                  okText="确认启用"
                  cancelText="取消"
                  onConfirm={() => void activateInboundSync()}
                >
                  <Button type="primary" loading={syncActivating}>
                    启用最新数据
                  </Button>
                </Popconfirm>
              )}
            </Space>
          </div>
        )}
      </section>
      <SyncInspectionDrawers
        inspection={inspection}
        previewConfig={{
          title: "待入库候选数据预览",
          width: 1120,
          columns: inboundPreviewColumns(inspection.preview),
          scroll: { x: 980, y: 480 }
        }}
        issuesConfig={{
          title: "待入库同步异常数据",
          width: 980,
          columns: inboundIssueColumns,
          rowKey: (issue) =>
            `${issue.code}-${issue.order_no}-${issue.sku}-${issue.source_site}-${issue.supplier_code}-${issue.message}`
        }}
        onDownload={downloadInboundIssues}
      />
    </>
  );
}
