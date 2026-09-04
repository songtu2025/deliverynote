import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message
} from "antd";
import {
  CheckCircleFilled,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  PlusOutlined,
  RightOutlined,
  SearchOutlined,
  SyncOutlined,
  UploadOutlined
} from "@ant-design/icons";
import type { TableProps, UploadFile, UploadProps } from "antd";

import { api, download } from "../api";
import { beijingDateTimeParts, formatBeijingDateTime } from "../dateTime";
import PurchaseSyncPanel from "./PurchaseSyncPanel";
import type {
  Batch,
  InputVersion,
  OverreceiptRuleVersion,
  SelfOperatedInboundSyncIssue,
  SelfOperatedInboundSyncPreview,
  SelfOperatedInboundSyncStatus,
  SelfOperatedOverreceiptRuleVersion
} from "../types";

export const STATUS_LABELS: Record<string, string> = {
  draft: "准备文件",
  preflight_ready: "预检通过",
  queued: "等待计算",
  running: "正在计算",
  succeeded: "计算完成",
  failed: "处理失败",
  expired: "任务已过期"
};

const STATUS_COLORS: Record<string, string> = {
  draft: "default",
  preflight_ready: "cyan",
  queued: "blue",
  running: "processing",
  succeeded: "success",
  failed: "error",
  expired: "warning"
};

const DELIVERY_VERSION_KINDS = [
  { value: "purchase", label: "采购需求" },
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "position", label: "MSKU定位" },
  { value: "template", label: "导出模板" }
];

const SELF_OPERATED_VERSION_KINDS = [
  { value: "product", label: "商品信息" },
  { value: "supplier", label: "供应商资料" },
  { value: "self_operated_inbound", label: "待入库 API 数据" },
  { value: "inbound_template", label: "积加入库模板" }
];

const STATUS_OPTIONS = Object.entries(STATUS_LABELS).map(([value, label]) => ({
  value,
  label
}));

type SelfOperatedIssueFilter = "all" | "warning" | "error";

const SELF_OPERATED_ISSUE_COLUMNS: NonNullable<
  TableProps<SelfOperatedInboundSyncIssue>["columns"]
> = [
  {
    title: "级别",
    dataIndex: "severity",
    width: 80,
    render: (value: SelfOperatedInboundSyncIssue["severity"]) => (
      <Tag color={value === "error" ? "error" : "warning"}>
        {value === "error" ? "错误" : "提醒"}
      </Tag>
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

function nextAction(batch: Batch): string {
  if (batch.status === "draft") {
    if (batch.workflow === "self_operated_inbound") {
      return batch.file_count && batch.inbound_file?.uploaded ? "执行预检" : "上传质检交货单";
    }
    return batch.file_count ? "执行预检" : "上传交货文件";
  }
  if (batch.status === "preflight_ready") return "启动计算";
  if (batch.status === "queued" || batch.status === "running") return "等待后台任务";
  if (batch.status === "failed" || batch.status === "expired") return "查看原因并重试";
  if (batch.download_ready) return "下载结果";
  if ((batch.summary?.manual_total ?? 0) > 0) return "审校待处理";
  return "生成导出";
}

function todayBatchName(workflow: "delivery" | "self_operated_inbound"): string {
  const parts = beijingDateTimeParts();
  const suffix = workflow === "self_operated_inbound" ? "自营仓入库批次" : "交货批次";
  return `${parts.year}-${parts.month}-${parts.day} ${suffix}`;
}

function isEmptySelfOperatedDraft(batch: Batch): boolean {
  return batch.workflow === "self_operated_inbound"
    && batch.status === "draft"
    && batch.file_count === 0
    && !batch.inbound_file?.uploaded;
}

function isEmptyDeliveryDraft(batch: Batch): boolean {
  return (batch.workflow ?? "delivery") === "delivery"
    && batch.status === "draft"
    && batch.file_count === 0;
}

function canDeleteBatch(batch: Batch): boolean {
  return batch.status !== "queued" && batch.status !== "running";
}

export function StatusTag({ status }: { status: string }) {
  return <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status] ?? status}</Tag>;
}

export default function BatchesPage({
  onOpen,
  workflow = "delivery",
  active = true,
  canActivatePurchaseSync = false,
  canDeleteBatches = false
}: {
  onOpen: (id: number) => void;
  workflow?: "delivery" | "self_operated_inbound";
  active?: boolean;
  canActivatePurchaseSync?: boolean;
  canDeleteBatches?: boolean;
}) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [overreceiptRules, setOverreceiptRules] = useState<OverreceiptRuleVersion[]>([]);
  const [selfOperatedRules, setSelfOperatedRules] = useState<SelfOperatedOverreceiptRuleVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [deliveryFiles, setDeliveryFiles] = useState<UploadFile[]>([]);
  const [sourceFiles, setSourceFiles] = useState<UploadFile[]>([]);
  const [syncStatus, setSyncStatus] = useState<SelfOperatedInboundSyncStatus | null>(null);
  const [syncStarting, setSyncStarting] = useState(false);
  const [syncActivating, setSyncActivating] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [syncDetailsOpen, setSyncDetailsOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [syncPreview, setSyncPreview] = useState<SelfOperatedInboundSyncPreview | null>(null);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [issuesError, setIssuesError] = useState("");
  const [syncIssues, setSyncIssues] = useState<SelfOperatedInboundSyncIssue[]>([]);
  const [issueFilter, setIssueFilter] = useState<SelfOperatedIssueFilter>("warning");
  const [cleaningEmpty, setCleaningEmpty] = useState(false);
  const [selectedBatchIds, setSelectedBatchIds] = useState<number[]>([]);
  const [deletingBatchIds, setDeletingBatchIds] = useState<number[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>();
  const loadedRef = useRef(false);
  const inboundSyncPollInFlightRef = useRef(false);
  const [form] = Form.useForm<{ name: string }>();

  const refreshVersions = useCallback(async () => {
    const nextVersions = await api<InputVersion[]>("/api/input-versions");
    setVersions(nextVersions);
    return nextVersions;
  }, []);

  const load = useCallback(async (
    background = false,
    knownInboundSyncStatus?: SelfOperatedInboundSyncStatus
  ) => {
    if (!background) setLoading(true);
    try {
      const [batchRows, versionRows, overreceiptRuleRows, inboundSyncStatus] = await Promise.all([
        api<Batch[]>("/api/batches"),
        api<InputVersion[]>("/api/input-versions"),
        workflow === "self_operated_inbound"
          ? api<SelfOperatedOverreceiptRuleVersion[]>("/api/self-operated-overreceipt-rule-versions")
          : api<OverreceiptRuleVersion[]>("/api/overreceipt-rule-versions"),
        workflow === "self_operated_inbound"
          ? knownInboundSyncStatus
            ? Promise.resolve(knownInboundSyncStatus)
            : api<SelfOperatedInboundSyncStatus>("/api/self-operated-inbound-sync")
          : Promise.resolve(null)
      ]);
      setBatches(batchRows);
      setVersions(versionRows);
      if (workflow === "self_operated_inbound") {
        setSelfOperatedRules(overreceiptRuleRows as SelfOperatedOverreceiptRuleVersion[]);
        setSyncStatus(inboundSyncStatus);
      } else {
        setOverreceiptRules(overreceiptRuleRows as OverreceiptRuleVersion[]);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取批次失败");
    } finally {
      loadedRef.current = true;
      if (!background) setLoading(false);
    }
  }, [workflow]);

  useEffect(() => {
    if (!loadedRef.current || active) void load(loadedRef.current);
  }, [active, load]);

  useEffect(() => {
    setSelectedBatchIds([]);
  }, [workflow]);

  useEffect(() => {
    const status = syncStatus?.job?.status;
    if (!active || workflow !== "self_operated_inbound" || (status !== "queued" && status !== "running")) {
      return undefined;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const pollSyncStatus = async () => {
      if (inboundSyncPollInFlightRef.current) {
        if (!cancelled) {
          timer = window.setTimeout(() => void pollSyncStatus(), 2000);
        }
        return;
      }
      inboundSyncPollInFlightRef.current = true;
      let shouldContinue = false;
      try {
        const next = await api<SelfOperatedInboundSyncStatus>(
          "/api/self-operated-inbound-sync"
        );
        if (cancelled) return;
        setSyncStatus(next);
        setSyncError("");
        shouldContinue = next.job?.status === "queued" || next.job?.status === "running";
        if (!shouldContinue) {
          await load(true, next);
        }
      } catch (error) {
        if (!cancelled) {
          setSyncError(error instanceof Error ? error.message : "读取同步状态失败");
          shouldContinue = true;
        }
      } finally {
        inboundSyncPollInFlightRef.current = false;
        if (!cancelled && shouldContinue) {
          timer = window.setTimeout(() => void pollSyncStatus(), 2000);
        }
      }
    };

    timer = window.setTimeout(() => void pollSyncStatus(), 2000);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [active, load, syncStatus?.job?.status, workflow]);

  const activeVersions = useMemo(
    () => Object.fromEntries(versions.filter((version) => version.active).map((version) => [version.kind, version])),
    [versions]
  );
  const versionKinds = workflow === "self_operated_inbound"
    ? SELF_OPERATED_VERSION_KINDS
    : DELIVERY_VERSION_KINDS;
  const missingKinds = versionKinds.filter((kind) => !activeVersions[kind.value]);
  const activeOverreceiptRule = overreceiptRules.find((rule) => rule.active);
  const activeSelfOperatedRule = selfOperatedRules.find((rule) => rule.active);
  const ready = missingKinds.length === 0;
  const emptySelfOperatedDrafts = useMemo(
    () => workflow === "self_operated_inbound"
      ? batches.filter(isEmptySelfOperatedDraft)
      : [],
    [batches, workflow]
  );
  const emptyDeliveryDrafts = useMemo(
    () => workflow === "delivery" ? batches.filter(isEmptyDeliveryDraft) : [],
    [batches, workflow]
  );
  const emptyDrafts = workflow === "self_operated_inbound"
    ? emptySelfOperatedDrafts
    : emptyDeliveryDrafts;

  const filtered = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase("zh-CN");
    return batches.filter((batch) => {
      const matchesQuery = !keyword || batch.name.toLocaleLowerCase("zh-CN").includes(keyword);
      const batchWorkflow = batch.workflow ?? "delivery";
      return batchWorkflow === workflow
        && matchesQuery
        && (!statusFilter || batch.status === statusFilter);
    });
  }, [batches, query, statusFilter, workflow]);

  const create = async () => {
    try {
      const values = await form.validateFields();
      let batch: Batch;
      if (workflow === "self_operated_inbound") {
        const files = sourceFiles.flatMap((file) => (
          file.originFileObj ? [file.originFileObj] : []
        ));
        if (!files.length) {
          message.warning("请至少选择一份质检交货单");
          return;
        }
        const formData = new FormData();
        formData.append("name", values.name);
        files.forEach((file) => formData.append("delivery_file", file));
        batch = await api<Batch>("/api/self-operated-batches", {
          method: "POST",
          body: formData
        });
      } else {
        const files = deliveryFiles.flatMap((file) => (
          file.originFileObj ? [file.originFileObj] : []
        ));
        if (!files.length) {
          message.warning("请至少选择一份交货文件");
          return;
        }
        const formData = new FormData();
        formData.append("name", values.name);
        files.forEach((file) => formData.append("files", file));
        batch = await api<Batch>("/api/batches/with-files", {
          method: "POST",
          body: formData
        });
      }
      setCreating(false);
      form.resetFields();
      setDeliveryFiles([]);
      setSourceFiles([]);
      onOpen(batch.id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建批次失败");
    }
  };

  const openCreate = () => {
    form.resetFields();
    setDeliveryFiles([]);
    setSourceFiles([]);
    form.setFieldsValue({ name: todayBatchName(workflow) });
    setCreating(true);
  };

  const closeCreate = () => {
    setCreating(false);
    form.resetFields();
    setDeliveryFiles([]);
    setSourceFiles([]);
  };

  const selectSourceFiles: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    setSourceFiles(fileList);
  };

  const selectDeliveryFiles: NonNullable<UploadProps["onChange"]> = ({ fileList }) => {
    setDeliveryFiles(fileList);
  };

  const startInboundSync = async () => {
    setSyncStarting(true);
    setSyncError("");
    try {
      await api("/api/self-operated-inbound-sync", { method: "POST" });
      message.success("待入库数据同步已进入后台队列");
      await load();
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启动同步失败");
    } finally {
      setSyncStarting(false);
    }
  };

  const activateInboundSync = async () => {
    const job = syncStatus?.job;
    if (!job?.candidate_version_id) return;
    setSyncActivating(true);
    setSyncError("");
    try {
      await api(`/api/self-operated-inbound-sync/${job.id}/activate`, {
        method: "POST"
      });
      message.success("最新待入库数据已启用，将用于新批次");
      await load();
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "启用失败");
    } finally {
      setSyncActivating(false);
    }
  };

  const openInboundPreview = async () => {
    const job = syncStatus?.job;
    if (!job?.candidate_version_id) return;
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewError("");
    setSyncPreview(null);
    try {
      setSyncPreview(await api<SelfOperatedInboundSyncPreview>(
        `/api/self-operated-inbound-sync/${job.id}/preview?limit=100`
      ));
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "读取候选数据失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const openInboundIssues = async (filter: SelfOperatedIssueFilter) => {
    const job = syncStatus?.job;
    if (!job) return;
    setIssueFilter(filter);
    setIssuesOpen(true);
    setIssuesLoading(true);
    setIssuesError("");
    setSyncIssues([]);
    try {
      setSyncIssues(await api<SelfOperatedInboundSyncIssue[]>(
        `/api/self-operated-inbound-sync/${job.id}/issues`
      ));
    } catch (error) {
      setIssuesError(error instanceof Error ? error.message : "读取异常数据失败");
    } finally {
      setIssuesLoading(false);
    }
  };

  const downloadInboundIssues = async () => {
    const job = syncStatus?.job;
    if (!job) return;
    try {
      await download(
        `/api/self-operated-inbound-sync/${job.id}/issues/download`,
        `待入库同步异常_${job.id}.xlsx`
      );
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "下载异常清单失败");
    }
  };

  const cleanEmptyBatches = async () => {
    setCleaningEmpty(true);
    try {
      const result = await api<{ deleted_count: number }>(
        workflow === "self_operated_inbound"
          ? "/api/self-operated-batches/empty"
          : "/api/batches/empty",
        {
          method: "DELETE"
        }
      );
      message.success(`已删除 ${result.deleted_count} 个空批次`);
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "清理空批次失败");
    } finally {
      setCleaningEmpty(false);
    }
  };

  const deleteSelectedBatches = async (batchIds: number[]) => {
    if (!batchIds.length) return;
    setDeletingBatchIds(batchIds);
    try {
      const result = await api<{
        deleted_count: number;
        deleted_ids: number[];
        file_cleanup_failed_ids: number[];
      }>("/api/batches", {
        method: "DELETE",
        body: JSON.stringify({ batch_ids: batchIds })
      });
      const deletedIds = new Set(result.deleted_ids);
      setBatches((rows) => rows.filter((batch) => !deletedIds.has(batch.id)));
      setSelectedBatchIds((ids) => ids.filter((id) => !deletedIds.has(id)));
      if (result.file_cleanup_failed_ids.length) {
        message.warning(
          `已删除 ${result.deleted_count} 个批次，但 ${result.file_cleanup_failed_ids.length} 个文件目录清理失败`
        );
      } else {
        message.success(`已永久删除 ${result.deleted_count} 个批次`);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除批次失败");
    } finally {
      setDeletingBatchIds([]);
    }
  };

  const deleting = deletingBatchIds.length > 0;
  const syncJob = syncStatus?.job ?? null;
  const syncRunning = syncJob?.status === "queued" || syncJob?.status === "running";
  const syncCandidateActive = Boolean(
    syncJob?.candidate_version_id
    && syncStatus?.active_version?.id === syncJob.candidate_version_id
  );
  const previewColumnWidths: Record<string, number> = {
    入库单号: 160,
    入库仓: 150,
    SKU: 190,
    平台站点: 230,
    "关联交货单/调拨单": 180,
    关联采购单: 160,
    应收货: 100
  };
  const previewColumns = Object.keys(previewColumnWidths)
    .filter((column) => syncPreview?.columns.includes(column)).map((column) => ({
    title: column === "应收货" ? "剩余应收货" : column,
    dataIndex: column,
    key: column,
    width: previewColumnWidths[column],
    ellipsis: true,
    render: (value: string | number | null) => (
      column === "平台站点" && value === "共享"
        ? <Tag color="warning">共享 · 不可自动匹配</Tag>
        : value ?? "—"
    )
  }));
  const filteredSyncIssues = syncIssues.filter((issue) => (
    issueFilter === "all" || issue.severity === issueFilter
  ));

  if (loading && !loadedRef.current) {
    return (
      <div
        className="page-shell batch-list-page"
        aria-busy="true"
        aria-label={workflow === "self_operated_inbound" ? "正在加载自营仓入库" : "正在加载交货批次"}
      >
        <Skeleton active title={{ width: 220 }} paragraph={{ rows: 8 }} />
        <Form form={form} component={false} />
      </div>
    );
  }
  return (
    <div className="page-shell batch-list-page">
      <div className="page-heading">
        <div>
          <Typography.Title level={2}>
            {workflow === "self_operated_inbound" ? "自营仓入库" : "交货批次"}
          </Typography.Title>
          <Typography.Text type="secondary">
            {workflow === "self_operated_inbound"
              ? "匹配质检交货单与待入库数据，生成积加入库文件。"
              : "按文件顺序扣减采购余额，批次创建时锁定资料版本。"}
          </Typography.Text>
        </div>
        <Space>
          {emptyDrafts.length > 0 && (
            <Popconfirm
              title={`删除 ${emptyDrafts.length} 个空批次？`}
              description={workflow === "self_operated_inbound"
                ? "仅删除未上传质检交货单和收货入库单的草稿，无法恢复。"
                : "仅删除未上传任何交货文件的草稿，无法恢复。"}
              okText="删除"
              cancelText="取消"
              onConfirm={() => void cleanEmptyBatches()}
            >
              <Button danger icon={<DeleteOutlined />} loading={cleaningEmpty}>
                清理空批次（{emptyDrafts.length}）
              </Button>
            </Popconfirm>
          )}
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!ready}
            title={ready ? "新建批次" : "请先补齐启用版本"}
            onClick={openCreate}
          >
            新建批次
          </Button>
        </Space>
      </div>

      {workflow === "delivery" && (
        <PurchaseSyncPanel
          versions={versions}
          canActivate={canActivatePurchaseSync}
          refreshVersions={refreshVersions}
          compact
        />
      )}

      {workflow === "self_operated_inbound" && (
        <section className="purchase-sync-card self-operated-sync-card" aria-label="积加待入库数据同步">
          <div className="purchase-sync-heading">
            <div>
              <Space size={8} wrap>
                <Typography.Title level={5}>积加待入库数据</Typography.Title>
                <Tag color="processing">待入库 + 部分入库</Tag>
              </Space>
              <Typography.Text type="secondary">
                同步待入库和部分入库采购单；启用后用于新批次。
              </Typography.Text>
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

          {!syncStatus?.configured && (
            <Alert type="warning" showIcon title="积加 API 尚未完成配置" />
          )}
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
              action={(
                <Space size={4} wrap>
                  <Button size="small" icon={<EyeOutlined />} onClick={() => void openInboundIssues("error")}>查看异常数据</Button>
                  <Button size="small" onClick={() => void downloadInboundIssues()}>下载问题清单</Button>
                </Space>
              )}
            />
          )}
          {syncJob?.status === "succeeded" && (
            <div className={`purchase-sync-result${syncCandidateActive ? " is-active" : ""}${syncDetailsOpen ? "" : " is-collapsed"}`}>
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
                  <div><dt>新增匹配项</dt><dd>{syncJob.diff.added_lines ?? 0}</dd></div>
                  <div><dt>数量变化项</dt><dd>{syncJob.diff.changed_lines ?? 0}</dd></div>
                  <div><dt>移除匹配项</dt><dd>{syncJob.diff.removed_lines ?? 0}</dd></div>
                  <div><dt>候选剩余应收总量</dt><dd>{syncJob.diff.after_quantity ?? 0}</dd></div>
                </dl>
              )}
              {syncDetailsOpen && syncJob.warning_count > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  title={`包含 ${syncJob.warning_count} 条“共享”站点数据`}
                  description="数据保留原值，但不能自动匹配，需业务复核。"
                  action={(
                    <Space size={4} wrap>
                      <Button size="small" onClick={() => void openInboundIssues("warning")}>查看异常数据</Button>
                      <Button size="small" onClick={() => void downloadInboundIssues()}>下载提醒清单</Button>
                    </Space>
                  )}
                />
              )}
              <Space className="purchase-sync-actions" size={8} wrap>
                <Button type="link" onClick={() => setSyncDetailsOpen((value) => !value)}>
                  {syncDetailsOpen ? "收起同步详情" : "查看同步详情"}
                </Button>
                {syncDetailsOpen && (
                  <Button icon={<EyeOutlined />} onClick={() => void openInboundPreview()}>预览候选数据</Button>
                )}
                {!syncCandidateActive && (
                  <Popconfirm
                    title="启用最新待入库数据？"
                    description="仅用于新批次；已有批次不变。"
                    okText="确认启用"
                    cancelText="取消"
                    onConfirm={() => void activateInboundSync()}
                  >
                    <Button type="primary" loading={syncActivating}>启用最新数据</Button>
                  </Popconfirm>
                )}
              </Space>
            </div>
          )}
        </section>
      )}

      <section className="batch-status-strip" aria-label="运行状态">
        <div className={`batch-status-item${ready ? " is-ready" : " is-warning"}`}>
          <span>基础资料</span>
          <strong>
            {versionKinds.length - missingKinds.length} / {versionKinds.length} {ready ? "已就绪" : "待补齐"}
          </strong>
          <small>{ready ? "可创建新批次" : `缺少：${missingKinds.map((kind) => kind.label).join("、")}`}</small>
        </div>
        <div className="batch-status-item">
          <span>{workflow === "self_operated_inbound" ? "待入库数据" : "采购数据"}</span>
          <strong>
            {activeVersions[workflow === "self_operated_inbound" ? "self_operated_inbound" : "purchase"]
              ? "已启用"
              : "待同步"}
          </strong>
          <small>
            {activeVersions[workflow === "self_operated_inbound" ? "self_operated_inbound" : "purchase"]?.name
              ?? "暂无启用版本"}
          </small>
        </div>
        <div className="batch-status-item">
          <span>超收规则</span>
          <strong>
            {(workflow === "self_operated_inbound" ? activeSelfOperatedRule : activeOverreceiptRule)
              ? "已启用"
              : "未启用"}
          </strong>
          <small>
            {workflow === "self_operated_inbound"
              ? activeSelfOperatedRule
                ? `${activeSelfOperatedRule.name} · ${activeSelfOperatedRule.allowance} 件`
                : "新批次超收数量为 0"
              : activeOverreceiptRule?.name ?? "新批次不会自动超收"}
          </small>
        </div>
      </section>

      <div
        className={`table-toolbar batch-list-toolbar${selectedBatchIds.length ? " is-selecting" : ""}`}
        aria-label={workflow === "self_operated_inbound" ? "入库批次筛选" : "交货批次筛选"}
      >
        <div className="batch-list-toolbar-heading">
          <strong>{workflow === "self_operated_inbound" ? "入库批次" : "交货批次"}</strong>
          <Typography.Text className="batch-result-count" type="secondary">
            {filtered.length} 个批次
          </Typography.Text>
          {selectedBatchIds.length > 0 && (
            <Typography.Text className="batch-selection-count" aria-live="polite">
              <CheckCircleFilled aria-hidden />
              已选 {selectedBatchIds.length} 项
            </Typography.Text>
          )}
          {canDeleteBatches && selectedBatchIds.length > 0 && (
            <Popconfirm
              title={`永久删除选中的 ${selectedBatchIds.length} 个批次？`}
              description="将删除批次记录、上传文件和结果文件，无法恢复。"
              okText="永久删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              disabled={!selectedBatchIds.length}
              onConfirm={() => void deleteSelectedBatches(selectedBatchIds)}
            >
              <Button
                danger
                size="small"
                icon={<DeleteOutlined />}
                aria-label={`删除已选（${selectedBatchIds.length}）`}
                disabled={!selectedBatchIds.length}
                loading={deleting}
              >
                批量删除
              </Button>
            </Popconfirm>
          )}
        </div>
        <div className="table-filter-field">
          <label htmlFor="batch-search">搜索</label>
          <Input
            id="batch-search"
            aria-label="搜索"
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索批次名称"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="table-filter-field">
          <label htmlFor="batch-status-filter">状态</label>
          <Select
            id="batch-status-filter"
            aria-label="状态"
            allowClear
            placeholder="全部状态"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={setStatusFilter}
          />
        </div>
      </div>

      <Table<Batch>
        className="batch-list-table"
        rowKey="id"
        rowSelection={canDeleteBatches ? {
          selectedRowKeys: selectedBatchIds,
          columnWidth: 52,
          onChange: (keys) => {
            setSelectedBatchIds(keys.map(Number));
          },
          getCheckboxProps: (batch) => ({
            disabled: !canDeleteBatch(batch),
            "aria-label": `选择批次 ${batch.name}`
          })
        } : undefined}
        loading={loading}
        dataSource={filtered}
        components={{
          table: (props) => <table {...props} aria-label={workflow === "self_operated_inbound" ? "自营仓入库批次列表" : "交货批次列表"} />
        }}
        locale={{ emptyText: <Empty description={query || statusFilter ? "没有匹配的批次" : "暂无批次"} /> }}
        pagination={filtered.length > 12 ? { pageSize: 12, showSizeChanger: false } : false}
        columns={[
          {
            title: "批次",
            dataIndex: "name",
            render: (value: string, batch) => (
              <Button className="batch-name-link" type="link" onClick={() => onOpen(batch.id)}>
                {value}
              </Button>
            )
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 130,
            render: (value: string) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">状态</span>
                <StatusTag status={value} />
              </div>
            )
          },
          {
            title: "文件 / 数量",
            width: 190,
            render: (_, batch) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">文件 / 数量</span>
                <span className="batch-volume">
                  {batch.workflow === "self_operated_inbound"
                    ? `${batch.file_count} 份质检单 + ${batch.inbound_file?.uploaded ? 1 : 0} 份待入库数据`
                    : `${batch.file_count} 个文件`}
                  {batch.summary && batch.summary.delivery_total > 0
                    ? " · 交货 " + batch.summary.delivery_total
                    : ""}
                </span>
              </div>
            )
          },
          {
            title: "下一步",
            width: 170,
            render: (_, batch) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">下一步</span>
                <span className="next-action">{nextAction(batch)}</span>
              </div>
            )
          },
          {
            title: "更新时间",
            dataIndex: "updated_at",
            width: 190,
            render: (value: string) => (
              <div className="batch-table-value">
                <span className="batch-cell-label">更新时间</span>
                <span>{formatBeijingDateTime(value)}</span>
              </div>
            )
          },
          {
            title: "操作",
            width: canDeleteBatches ? 170 : 100,
            render: (_, batch) => (
              <Space className="batch-row-actions" size={0}>
                <Button
                  className="batch-open-action"
                  type="link"
                  aria-label={"打开 " + batch.name}
                  onClick={() => onOpen(batch.id)}
                >
                  <Space size={4}>打开<RightOutlined /></Space>
                </Button>
                {canDeleteBatches && (
                  <Popconfirm
                    title={`永久删除“${batch.name}”？`}
                    description="将删除批次记录、上传文件和结果文件，无法恢复。"
                    okText="永久删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    disabled={!canDeleteBatch(batch)}
                    onConfirm={() => void deleteSelectedBatches([batch.id])}
                  >
                    <Button
                      danger
                      type="link"
                      aria-label={`删除批次 ${batch.name}`}
                      disabled={!canDeleteBatch(batch)}
                      loading={deletingBatchIds.includes(batch.id)}
                      title={canDeleteBatch(batch) ? "删除批次" : "运行中的批次不能删除"}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                )}
              </Space>
            )
          }
        ]}
      />

      <Modal
        title={workflow === "self_operated_inbound" ? "新建自营仓入库批次" : "新建交货批次"}
        open={creating}
        onCancel={closeCreate}
        onOk={() => void create()}
        okText={workflow === "self_operated_inbound" ? "创建批次" : "创建并上传文件"}
        cancelText="取消"
        okButtonProps={{
          disabled: workflow === "self_operated_inbound"
            ? !sourceFiles.length
            : !deliveryFiles.length
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="批次名称"
            name="name"
            rules={[{ required: true, message: "请输入批次名称" }]}
          >
            <Input placeholder={workflow === "self_operated_inbound" ? "例如：2026-08-21 自营仓入库批次" : "例如：2026-07-21 交货批次"} />
          </Form.Item>
          {workflow === "delivery" && (
            <>
              <Form.Item label="交货文件" required>
                <Upload
                  accept=".xls,.xlsx"
                  multiple
                  beforeUpload={() => false}
                  fileList={deliveryFiles}
                  onChange={selectDeliveryFiles}
                >
                  <Button icon={<UploadOutlined />}>选择交货文件</Button>
                </Upload>
              </Form.Item>
              <Typography.Text type="secondary">
                至少选择一份；校验通过后创建批次。
              </Typography.Text>
            </>
          )}
          {workflow === "self_operated_inbound" && (
            <>
              <Form.Item label="质检交货单" required>
                <Upload
                  accept=".xls,.xlsx"
                  multiple
                  beforeUpload={() => false}
                  fileList={sourceFiles}
                  onChange={selectSourceFiles}
                >
                  <Button icon={<UploadOutlined />}>选择质检交货单</Button>
                </Upload>
              </Form.Item>
              <Typography.Text type="secondary">
                可同时选择多份；系统将按列表顺序共享扣减待入库余额和超收额度。
              </Typography.Text>
              <Alert
                type="info"
                showIcon
                title="锁定待入库数据版本"
                description={activeVersions.self_operated_inbound
                  ? `本批次将使用：${activeVersions.self_operated_inbound.name}`
                  : "请先同步并启用待入库 API 数据"}
              />
            </>
          )}
        </Form>
        <div className="locked-version-preview">
          <Typography.Text strong>锁定版本</Typography.Text>
          {versionKinds.map((kind) => (
            <div key={kind.value}>
              <span>{kind.label}</span>
              <strong>{activeVersions[kind.value]?.name ?? "未启用"}</strong>
            </div>
          ))}
          <div>
            <span>超收规则</span>
            <strong>
              {workflow === "self_operated_inbound"
                ? activeSelfOperatedRule?.name ?? "未启用（允许超收 0 件）"
                : activeOverreceiptRule?.name ?? "未启用（不自动超收）"}
            </strong>
          </div>
        </div>
      </Modal>

      <Drawer
        rootClassName="purchase-sync-issues-drawer"
        title="待入库候选数据预览"
        open={previewOpen}
        size={1120}
        destroyOnHidden
        onClose={() => setPreviewOpen(false)}
      >
        {previewError ? (
          <Alert type="error" showIcon title="无法读取候选数据" description={previewError} />
        ) : (
          <>
            <Typography.Paragraph type="secondary">
              共 {syncPreview?.total ?? 0} 行，当前展示前 {Math.min(syncPreview?.total ?? 0, 100)} 行。
            </Typography.Paragraph>
            <Table
              rowKey={(row) => String(row._row_number)}
              loading={previewLoading}
              dataSource={syncPreview?.rows ?? []}
              columns={previewColumns}
              scroll={{ x: 980, y: 480 }}
              pagination={false}
              size="small"
              locale={{ emptyText: "当前候选版本没有可预览数据" }}
            />
          </>
        )}
      </Drawer>

      <Drawer
        rootClassName="purchase-sync-issues-drawer"
        title="待入库同步异常数据"
        open={issuesOpen}
        size={980}
        destroyOnHidden
        extra={<Button size="small" icon={<DownloadOutlined />} onClick={() => void downloadInboundIssues()}>下载完整清单</Button>}
        onClose={() => setIssuesOpen(false)}
      >
        <div className="purchase-sync-issues-toolbar">
          <Typography.Text type="secondary">
            共 {syncIssues.length} 条，显示 {filteredSyncIssues.length} 条。
          </Typography.Text>
          <Space size={6} wrap>
            <Typography.Text type="secondary">筛选：</Typography.Text>
            {([ ["warning", "共享站点提醒"], ["error", "映射错误"], ["all", "全部"] ] as Array<[SelfOperatedIssueFilter, string]>).map(([value, label]) => (
              <Button key={value} size="small" type={issueFilter === value ? "primary" : "default"} onClick={() => setIssueFilter(value)}>
                {label}
              </Button>
            ))}
          </Space>
        </div>
        {issuesError ? (
          <Alert type="error" showIcon title="无法读取异常数据" description={issuesError} />
        ) : (
          <Table<SelfOperatedInboundSyncIssue>
            className="purchase-sync-issues-table"
            rowKey={(issue) => `${issue.code}-${issue.order_no}-${issue.sku}-${issue.source_site}-${issue.supplier_code}-${issue.message}`}
            loading={issuesLoading}
            dataSource={filteredSyncIssues}
            pagination={filteredSyncIssues.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
            size="small"
            scroll={{ x: "max-content" }}
            locale={{ emptyText: "当前筛选条件下没有异常数据" }}
            columns={SELF_OPERATED_ISSUE_COLUMNS}
          />
        )}
      </Drawer>
    </div>
  );
}
