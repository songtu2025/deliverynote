import { useState } from "react";
import { Alert, Button, Popconfirm, Space, Skeleton, Tag, Typography } from "antd";
import { CheckCircleFilled, EyeOutlined, SyncOutlined } from "@ant-design/icons";
import { formatBeijingDateTime } from "../dateTime";
import { getPurchaseSyncPreview, getPurchaseSyncIssues } from "../syncApi";
import type { InputVersion } from "../types";
import { usePurchaseSync } from "./batches/usePurchaseSync";
import { useSyncInspection } from "./batches/useSyncInspection";
import SyncInspectionDrawers from "./batches/SyncInspectionDrawers";
import { purchasePreviewColumns, purchaseIssueColumns } from "./batches/purchaseSyncColumns";

interface PurchaseSyncPanelProps {
  versions: InputVersion[];
  canActivate: boolean;
  refreshVersions: () => Promise<InputVersion[]>;
  compact?: boolean;
}

export default function PurchaseSyncPanel({
  versions,
  canActivate,
  refreshVersions,
  compact = false
}: PurchaseSyncPanelProps) {
  const {
    syncStatus,
    syncError,
    syncStarting,
    syncActivating,
    syncJob,
    syncCandidate,
    running,
    configured,
    progress,
    startSync,
    activateCandidate,
    downloadIssues
  } = usePurchaseSync(versions, canActivate, refreshVersions);
  const [detailsOpen, setDetailsOpen] = useState(!compact);
  const inspection = useSyncInspection({
    jobId: syncJob?.id,
    hasCandidate: Boolean(syncJob?.candidate_version_id),
    readPreview: getPurchaseSyncPreview,
    readIssues: getPurchaseSyncIssues
  });
  const { openPreview, openIssues } = inspection;
  if (syncStatus === null && !syncError) {
    return (
      <section
        className={`purchase-sync-card${compact ? " purchase-sync-card--compact" : ""}`}
        aria-busy="true"
        aria-label="正在读取积加采购数据同步状态"
      >
        <Skeleton active title={{ width: 180 }} paragraph={{ rows: compact ? 1 : 2 }} />
      </section>
    );
  }

  return (
    <>
      <section
        className={`purchase-sync-card${compact ? " purchase-sync-card--compact" : ""}`}
        aria-label="积加采购数据同步"
      >
        <div className="purchase-sync-heading">
          <div>
            <Space size={8} wrap>
              <Typography.Title level={5}>积加采购数据</Typography.Title>
              <Tag className="purchase-sync-scope-tag">待交货 + 交货中</Tag>
            </Space>
            {!compact && <Typography.Text type="secondary">同步未交清采购单；启用后用于新批次。</Typography.Text>}
          </div>
          <Button
            type="primary"
            icon={<SyncOutlined />}
            loading={syncStarting}
            disabled={!configured || running || syncActivating}
            onClick={() => void startSync()}
          >
            {running ? "正在同步" : "同步采购数据"}
          </Button>
        </div>

        {!configured && <Alert type="warning" showIcon title="积加 API 尚未完成配置" />}
        {syncError && <Alert type="error" showIcon title="同步操作失败" description={syncError} />}

        {running && syncJob && (
          <div className="purchase-sync-progress" aria-label="采购同步进度">
            <div>
              <strong>{syncJob.status === "queued" ? "等待后台任务" : "正在读取采购单明细"}</strong>
              <span>
                {syncJob.processed_orders}/{syncJob.total_orders || "—"} 张采购单
              </span>
            </div>
            <div className="purchase-sync-progress-track" aria-valuenow={progress} role="progressbar">
              <span style={{ width: `${progress}%` }} />
            </div>
            <Typography.Text type="secondary">
              {syncJob.current_order ? `当前采购单：${syncJob.current_order}` : "正在准备接口数据"}
            </Typography.Text>
          </div>
        )}

        {syncJob?.status === "blocked" && (
          <Alert
            type="warning"
            showIcon
            title={`发现 ${syncJob.issue_count} 个基础资料映射问题，未生成候选版本`}
            description="核对积加站点、SKU 或目的仓后重新同步；当前启用版本不变。"
            action={
              <Space size={4} wrap>
                <Button size="small" onClick={() => void openIssues("error")}>
                  查看异常数据
                </Button>
                <Button size="small" onClick={() => void downloadIssues()}>
                  下载问题清单
                </Button>
              </Space>
            }
          />
        )}

        {syncJob?.status === "failed" && (
          <Alert type="error" showIcon title="本次同步失败" description={syncJob.error_message ?? "请稍后重试"} />
        )}

        {syncJob?.status === "succeeded" && (
          <div
            className={`purchase-sync-result${syncCandidate?.active ? " is-active" : ""}${detailsOpen ? "" : " is-collapsed"}`}
          >
            <div className="purchase-sync-result-copy">
              <CheckCircleFilled />
              <div>
                <strong>{syncCandidate?.active ? "数据已启用" : "同步完成，待启用"}</strong>
                <Typography.Text type="secondary">
                  {detailsOpen
                    ? `接口明细 ${syncJob.raw_detail_count} 行，保留 ${syncJob.eligible_detail_count} 行，过滤已交清 ${syncJob.filtered_detail_count} 行`
                    : `保留 ${syncJob.eligible_detail_count} 行 · ${formatBeijingDateTime(syncJob.finished_at ?? syncJob.created_at)}`}
                </Typography.Text>
              </div>
            </div>
            {detailsOpen && (
              <dl className="purchase-sync-diff">
                <div>
                  <dt>新增匹配项</dt>
                  <dd>{syncJob.diff.added_lines ?? 0}</dd>
                </div>
                <div>
                  <dt>余额变化项</dt>
                  <dd>{syncJob.diff.changed_lines ?? 0}</dd>
                </div>
                <div>
                  <dt>移除匹配项</dt>
                  <dd>{syncJob.diff.removed_lines ?? 0}</dd>
                </div>
                <div>
                  <dt>候选未交总量</dt>
                  <dd>{syncJob.diff.after_quantity ?? 0}</dd>
                </div>
              </dl>
            )}
            {detailsOpen && syncJob.warning_count > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`包含 ${syncJob.warning_count} 条“共享”站点数据`}
                description="数据保留原值，但不能参与交货匹配；启用前需业务复核。"
                action={
                  <Space size={4} wrap>
                    <Button size="small" onClick={() => void openIssues("warning")}>
                      查看异常数据
                    </Button>
                    <Button size="small" onClick={() => void downloadIssues()}>
                      下载提醒清单
                    </Button>
                  </Space>
                }
              />
            )}
            <Space className="purchase-sync-actions" size={8} wrap>
              <Button type="link" onClick={() => setDetailsOpen((value) => !value)}>
                {detailsOpen ? "收起同步详情" : "查看同步详情"}
              </Button>
              {detailsOpen && syncCandidate && (
                <Button icon={<EyeOutlined />} onClick={() => void openPreview()}>
                  预览候选数据
                </Button>
              )}
              {!syncCandidate?.active && canActivate && (
                <Popconfirm
                  title="启用这份同步数据？"
                  description="仅用于新批次；已有批次不变。"
                  okText="确认启用"
                  cancelText="取消"
                  disabled={!syncCandidate}
                  onConfirm={() => void activateCandidate()}
                >
                  <Button type="primary" loading={syncActivating} disabled={!syncCandidate}>
                    启用最新数据
                  </Button>
                </Popconfirm>
              )}
              {!syncCandidate?.active && !canActivate && syncCandidate && (
                <Typography.Text className="purchase-sync-permission-note" type="secondary">
                  待管理员启用
                </Typography.Text>
              )}
            </Space>
          </div>
        )}
      </section>

      <SyncInspectionDrawers
        inspection={inspection}
        previewConfig={{
          title: "采购候选数据预览",
          width: 980,
          columns: purchasePreviewColumns,
          scroll: { x: 830, y: 520 }
        }}
        issuesConfig={{
          title: "采购同步异常数据",
          width: 980,
          columns: purchaseIssueColumns,
          rowKey: (issue) => `${issue.code}-${issue.po_code}-${issue.sku}-${issue.source_site}-${issue.supplier_code}`
        }}
        onDownload={downloadIssues}
      />
    </>
  );
}
