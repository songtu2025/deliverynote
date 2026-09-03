import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Popconfirm,
  Space,
  Skeleton,
  Table,
  Tag,
  Typography,
  message
} from "antd";
import { CheckCircleFilled, DownloadOutlined, EyeOutlined, SyncOutlined } from "@ant-design/icons";
import type { TableProps } from "antd";

import { api, download } from "../api";
import { formatBeijingDateTime } from "../dateTime";
import type {
  InputVersion,
  PurchaseSyncIssue,
  PurchaseSyncPreview,
  PurchaseSyncStatus
} from "../types";

type SyncIssueFilter = "all" | "warning" | "error";
type PurchasePreviewRow = PurchaseSyncPreview["rows"][number];

const previewColumns: NonNullable<TableProps<PurchasePreviewRow>["columns"]> = [
  { title: "单据状态", dataIndex: "单据状态", width: 90 },
  { title: "供应商", dataIndex: "供应商", width: 140, ellipsis: true },
  { title: "SKU", dataIndex: "SKU", width: 160, ellipsis: true },
  {
    title: "平台站点",
    dataIndex: "平台站点",
    width: 200,
    ellipsis: true,
    render: (value: string | null) => (
      value === "共享" ? <Tag color="warning">共享 · 不可自动匹配</Tag> : value || "—"
    )
  },
  { title: "目的仓", dataIndex: "目的仓", width: 150, ellipsis: true },
  { title: "未交量", dataIndex: "未交量", width: 90, align: "right" }
];

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
  const [syncStatus, setSyncStatus] = useState<PurchaseSyncStatus | null>(null);
  const [syncError, setSyncError] = useState("");
  const [syncStarting, setSyncStarting] = useState(false);
  const [syncActivating, setSyncActivating] = useState(false);
  const [syncAttempt, setSyncAttempt] = useState(0);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [preview, setPreview] = useState<PurchaseSyncPreview | null>(null);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [issuesError, setIssuesError] = useState("");
  const [issues, setIssues] = useState<PurchaseSyncIssue[]>([]);
  const [issueFilter, setIssueFilter] = useState<SyncIssueFilter>("warning");
  const [detailsOpen, setDetailsOpen] = useState(!compact);
  const refreshedCandidateRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const loadStatus = async () => {
      try {
        const next = await api<PurchaseSyncStatus>("/api/purchase-sync");
        if (cancelled) return;
        setSyncStatus(next);
        setSyncError("");
        const candidateId = next.job?.candidate_version_id ?? null;
        if (
          next.job?.status === "succeeded"
          && candidateId
          && !versions.some((version) => version.id === candidateId)
          && refreshedCandidateRef.current !== candidateId
        ) {
          refreshedCandidateRef.current = candidateId;
          await refreshVersions();
        }
        if (next.job?.status === "queued" || next.job?.status === "running") {
          timer = setTimeout(() => void loadStatus(), 2000);
        }
      } catch (error) {
        if (!cancelled) {
          setSyncError(error instanceof Error ? error.message : "读取同步状态失败");
        }
      }
    };

    void loadStatus();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [refreshVersions, syncAttempt, versions]);

  const syncJob = syncStatus?.job ?? null;
  const syncCandidate = syncJob?.candidate_version_id
    ? versions.find((version) => version.id === syncJob.candidate_version_id) ?? null
    : null;
  const running = syncJob?.status === "queued" || syncJob?.status === "running";
  const configured = syncStatus?.configured ?? true;
  const progress = syncJob?.total_orders
    ? Math.round((syncJob.processed_orders / syncJob.total_orders) * 100)
    : 0;
  const filteredIssues = issues.filter((issue) => (
    issueFilter === "all" || issue.severity === issueFilter
  ));
  const issueColumns = useMemo<NonNullable<TableProps<PurchaseSyncIssue>["columns"]>>(
    () => [
      {
        title: "级别",
        dataIndex: "severity",
        width: 88,
        render: (severity: PurchaseSyncIssue["severity"]) => (
          <Tag color={severity === "error" ? "error" : "warning"}>
            {severity === "error" ? "错误" : "提醒"}
          </Tag>
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
    ],
    []
  );

  const startSync = async () => {
    if (syncStarting || running) return;
    setSyncStarting(true);
    setSyncError("");
    try {
      await api("/api/purchase-sync", { method: "POST" });
      setSyncAttempt((value) => value + 1);
      message.success("采购数据同步已进入后台队列");
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启动同步失败");
    } finally {
      setSyncStarting(false);
    }
  };

  const activateCandidate = async () => {
    if (!syncCandidate || !canActivate || syncActivating) return;
    setSyncActivating(true);
    setSyncError("");
    try {
      await api<InputVersion>(`/api/input-versions/${syncCandidate.id}/activate`, { method: "POST" });
      await refreshVersions();
      message.success(`${syncCandidate.name} 已启用，将用于新批次`);
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启用失败");
    } finally {
      setSyncActivating(false);
    }
  };

  const downloadIssues = async () => {
    if (!syncJob) return;
    try {
      await download(
        `/api/purchase-sync/${syncJob.id}/issues/download`,
        `采购同步问题_${syncJob.id}.xlsx`
      );
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "下载问题清单失败");
    }
  };

  const openPreview = async () => {
    if (!syncJob?.candidate_version_id) return;
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewError("");
    setPreview(null);
    try {
      setPreview(await api<PurchaseSyncPreview>(
        `/api/purchase-sync/${syncJob.id}/preview?limit=100`
      ));
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "读取候选数据失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const openIssues = async (filter: SyncIssueFilter) => {
    if (!syncJob) return;
    setIssueFilter(filter);
    setIssuesOpen(true);
    setIssuesError("");
    setIssuesLoading(true);
    try {
      setIssues(await api<PurchaseSyncIssue[]>(`/api/purchase-sync/${syncJob.id}/issues`));
    } catch (error) {
      setIssuesError(error instanceof Error ? error.message : "读取异常数据失败");
    } finally {
      setIssuesLoading(false);
    }
  };

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
            {!compact && (
              <Typography.Text type="secondary">
                同步未交清采购单；启用后用于新批次。
              </Typography.Text>
            )}
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
              <span>{syncJob.processed_orders}/{syncJob.total_orders || "—"} 张采购单</span>
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
            action={(
              <Space size={4} wrap>
                <Button size="small" onClick={() => void openIssues("error")}>查看异常数据</Button>
                <Button size="small" onClick={() => void downloadIssues()}>下载问题清单</Button>
              </Space>
            )}
          />
        )}

        {syncJob?.status === "failed" && (
          <Alert type="error" showIcon title="本次同步失败" description={syncJob.error_message ?? "请稍后重试"} />
        )}

        {syncJob?.status === "succeeded" && (
          <div className={`purchase-sync-result${syncCandidate?.active ? " is-active" : ""}${detailsOpen ? "" : " is-collapsed"}`}>
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
                <div><dt>新增匹配项</dt><dd>{syncJob.diff.added_lines ?? 0}</dd></div>
                <div><dt>余额变化项</dt><dd>{syncJob.diff.changed_lines ?? 0}</dd></div>
                <div><dt>移除匹配项</dt><dd>{syncJob.diff.removed_lines ?? 0}</dd></div>
                <div><dt>候选未交总量</dt><dd>{syncJob.diff.after_quantity ?? 0}</dd></div>
              </dl>
            )}
            {detailsOpen && syncJob.warning_count > 0 && (
              <Alert
                type="warning"
                showIcon
                title={`包含 ${syncJob.warning_count} 条“共享”站点数据`}
                description="数据保留原值，但不能参与交货匹配；启用前需业务复核。"
                action={(
                  <Space size={4} wrap>
                    <Button size="small" onClick={() => void openIssues("warning")}>查看异常数据</Button>
                    <Button size="small" onClick={() => void downloadIssues()}>下载提醒清单</Button>
                  </Space>
                )}
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
                  <Button type="primary" loading={syncActivating} disabled={!syncCandidate}>启用最新数据</Button>
                </Popconfirm>
              )}
              {!syncCandidate?.active && !canActivate && syncCandidate && (
                <Typography.Text className="purchase-sync-permission-note" type="secondary">待管理员启用</Typography.Text>
              )}
            </Space>
          </div>
        )}

      </section>

      <Drawer
        rootClassName="purchase-sync-issues-drawer"
        title="采购候选数据预览"
        size={980}
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
            <Table<PurchasePreviewRow>
              size="small"
              loading={previewLoading}
              columns={previewColumns}
              dataSource={preview?.rows ?? []}
              rowKey={(row) => String(row._row_number)}
              pagination={false}
              scroll={{ x: 830, y: 520 }}
              locale={{ emptyText: "当前候选版本没有可预览数据" }}
            />
          </>
        )}
      </Drawer>

      <Drawer
        rootClassName="purchase-sync-issues-drawer"
        title="采购同步异常数据"
        size={980}
        open={issuesOpen}
        destroyOnHidden
        extra={<Button size="small" icon={<DownloadOutlined />} onClick={() => void downloadIssues()}>下载完整清单</Button>}
        onClose={() => setIssuesOpen(false)}
      >
        <div className="purchase-sync-issues-toolbar">
          <Typography.Text type="secondary">共 {issues.length} 条，显示 {filteredIssues.length} 条。</Typography.Text>
          <Space size={6} wrap>
            <Typography.Text type="secondary">筛选：</Typography.Text>
            {([ ["warning", "共享站点提醒"], ["error", "映射错误"], ["all", "全部"] ] as Array<[SyncIssueFilter, string]>).map(([value, label]) => (
              <Button key={value} size="small" type={issueFilter === value ? "primary" : "default"} onClick={() => setIssueFilter(value)}>
                {label}
              </Button>
            ))}
          </Space>
        </div>
        {issuesError ? (
          <Alert type="error" showIcon title="无法读取异常数据" description={issuesError} />
        ) : (
          <Table<PurchaseSyncIssue>
            className="purchase-sync-issues-table"
            rowKey={(issue) => `${issue.code}-${issue.po_code}-${issue.sku}-${issue.source_site}-${issue.supplier_code}`}
            size="small"
            loading={issuesLoading}
            columns={issueColumns}
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
