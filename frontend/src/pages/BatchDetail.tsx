import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Empty,
  Popconfirm,
  Space,
  Spin,
  Steps,
  Table,
  Tooltip,
  Typography,
  Upload
} from "antd";
import type { UploadProps } from "antd";
import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowUpOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ExportOutlined,
  LockOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined
} from "@ant-design/icons";

import { api, ApiError, download } from "../api";
import { formatBeijingDateTime } from "../dateTime";
import type { Batch, BatchFile, DeliveryException, InputVersion, Job } from "../types";
import StatusTag from "../BatchStatusTag";
import ExceptionReviewTable from "./batch-detail/ExceptionReviewTable";
import ExceptionReviewDrawer from "./batch-detail/ExceptionReviewDrawer";
import { useExceptionEditor } from "./batch-detail/useExceptionEditor";
import { useExceptionReview } from "./useExceptionReview";

const VERSION_LABELS: Record<string, string> = {
  purchase: "采购需求",
  product: "商品信息",
  supplier: "供应商资料",
  position: "MSKU定位",
  template: "导出模板",
  inbound_template: "积加入库模板"
};

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function isActiveJob(job: Job | undefined): job is Job {
  return Boolean(job && (job.status === "queued" || job.status === "running"));
}

export default function BatchDetail({
  batchId,
  onBack,
  canRefreshSupplierVersion = false
}: {
  batchId: number;
  onBack: () => void;
  canRefreshSupplierVersion?: boolean;
}) {
  const { message } = AntApp.useApp();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [activeSupplierVersion, setActiveSupplierVersion] = useState<InputVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [splitTarget, setSplitTarget] = useState<DeliveryException | null>(null);
  const [lockedDataOpen, setLockedDataOpen] = useState(true);
  const pollingJob = useRef<number | null>(null);
  const announcedJobs = useRef(new Set<number>());
  const reviewSection = useRef<HTMLDivElement | null>(null);
  const loadRequestRef = useRef(0);
  const review = useExceptionReview(batchId, batch?.status);
  const { setExceptionsLoading, fetchExceptionPage, applyExceptionPage } = review;

  const load = useCallback(
    async (silent = false) => {
      const request = ++loadRequestRef.current;
      if (!silent) {
        setLoading(true);
        setLoadError(null);
      }
      setExceptionsLoading(true);
      try {
        const batchRequest = api<Batch>(`/api/batches/${batchId}`).then((result) => {
          if (request !== loadRequestRef.current) return;
          setBatch(result);
          if (!silent) setLoading(false);
        });
        const exceptionsRequest = fetchExceptionPage().then((result) => {
          if (request !== loadRequestRef.current) return result;
          const pendingTarget = applyExceptionPage(result);
          if (pendingTarget !== undefined) setSplitTarget(pendingTarget);
          return result;
        });
        const versionsRequest = canRefreshSupplierVersion
          ? api<InputVersion[]>("/api/input-versions").then((versions) => {
              if (request !== loadRequestRef.current) return;
              setActiveSupplierVersion(
                versions.find((version) => version.kind === "supplier" && version.active) ?? null
              );
            })
          : Promise.resolve();
        const [, loadedPage] = await Promise.all([batchRequest, exceptionsRequest, versionsRequest]);
        if (request === loadRequestRef.current) setLoadError(null);
        return request === loadRequestRef.current ? loadedPage : null;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          // 刷新遇到会话过期时终止后续成功提示，认证提示由应用统一处理。
          if (silent) throw error;
          return null;
        }
        if (request === loadRequestRef.current) {
          setLoadError(error instanceof Error ? error.message : "读取批次失败");
        }
        return null;
      } finally {
        if (request === loadRequestRef.current) {
          if (!silent) setLoading(false);
          setExceptionsLoading(false);
        }
      }
    },
    [batchId, canRefreshSupplierVersion, fetchExceptionPage, applyExceptionPage, setExceptionsLoading]
  );

  useEffect(() => {
    void load();
  }, [load]);

  const activeJob = useMemo(() => {
    const jobs = batch?.jobs;
    if (isActiveJob(jobs?.compute)) return jobs.compute;
    if (isActiveJob(jobs?.export)) return jobs.export;
    return undefined;
  }, [batch?.jobs]);

  const refreshAfterJob = useEffectEvent(() => load(true));
  const activeJobId = activeJob?.id;
  const activeJobStatus = activeJob?.status;
  useEffect(() => {
    if (!activeJobId || pollingJob.current === activeJobId) return;
    let cancelled = false;
    pollingJob.current = activeJobId;

    const poll = async () => {
      try {
        const job = await api<Job>(`/api/jobs/${activeJobId}`);
        if (cancelled) return;
        if (job.status === "succeeded" || job.status === "failed") {
          pollingJob.current = null;
          await refreshAfterJob();
          if (!announcedJobs.current.has(job.id)) {
            announcedJobs.current.add(job.id);
            if (job.status === "succeeded") {
              message.success(job.kind === "compute" ? "批次计算完成" : "导出文件已生成");
            } else {
              message.error(job.error_message ?? "后台任务失败");
            }
          }
          return;
        }
        await wait(1500);
        if (!cancelled) void poll();
      } catch (error) {
        pollingJob.current = null;
        if (!cancelled && !(error instanceof ApiError && error.status === 401)) {
          message.error(error instanceof Error ? error.message : "读取任务状态失败");
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (pollingJob.current === activeJobId) pollingJob.current = null;
    };
  }, [activeJobId, activeJobStatus, message]);

  const totals = useMemo(
    () =>
      batch?.summary ?? {
        delivery_total: 0,
        import_total: 0,
        manual_total: 0,
        conserved: true
      },
    [batch]
  );

  const files = useMemo(() => batch?.files ?? [], [batch?.files]);
  const fileById = useMemo(() => Object.fromEntries(files.map((file) => [file.id, file])), [files]);

  const runAction = async (name: string, operation: () => Promise<void>) => {
    setAction(name);
    try {
      await operation();
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        message.error(error instanceof Error ? error.message : "操作失败");
      }
    } finally {
      setAction(null);
    }
  };

  const uploadFile: NonNullable<UploadProps["customRequest"]> = async (options) => {
    await runAction("upload", async () => {
      const formData = new FormData();
      formData.append("file", options.file as File);
      await api<BatchFile>(`/api/batches/${batchId}/files`, {
        method: "POST",
        body: formData
      });
      options.onSuccess?.({});
      await load(true);
      message.success(`${selfOperated ? "质检交货单" : "交货文件"}已上传，预检状态已更新`);
    });
  };

  const uploadInboundFile: NonNullable<UploadProps["customRequest"]> = async (options) => {
    await runAction("upload-inbound", async () => {
      const formData = new FormData();
      formData.append("file", options.file as File);
      await api<Batch>(`/api/self-operated-batches/${batchId}/inbound-file`, {
        method: "POST",
        body: formData
      });
      options.onSuccess?.({});
      await load(true);
      message.success("自营仓入库单已上传，预检状态已更新");
    });
  };

  const removeFile = async (file: BatchFile) => {
    await runAction("delete", async () => {
      await api<Batch>(`/api/batches/${batchId}/files/${file.id}`, { method: "DELETE" });
      await load(true);
      message.success(`${file.original_name} 已删除，其余文件已自动重排`);
    });
  };

  const move = async (fileId: number, offset: number) => {
    const ids = files.map((file) => file.id);
    const index = ids.indexOf(fileId);
    const next = index + offset;
    if (index < 0 || next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    await runAction("order", async () => {
      await api<Batch>(`/api/batches/${batchId}/files/order`, {
        method: "PUT",
        body: JSON.stringify({ file_ids: ids })
      });
      await load(true);
      message.info("处理顺序已更新，需要重新预检");
    });
  };

  const preflight = () =>
    runAction("preflight", async () => {
      await api<Batch>(`/api/batches/${batchId}/preflight`, { method: "POST" });
      await load(true);
      message.success("所有基础资料和交货文件均已通过预检");
    });

  const refreshSupplierVersion = () =>
    runAction("refresh-supplier-version", async () => {
      const updated = await api<Batch>(`/api/batches/${batchId}/refresh-supplier-version`, { method: "POST" });
      setBatch(updated);
      await load(true);
      message.success("批次已采用当前供应商资料");
    });

  const compute = () =>
    runAction("compute", async () => {
      await api<Job>(`/api/batches/${batchId}/compute`, { method: "POST" });
      await load(true);
      message.info("计算任务已提交，可以离开页面，返回后状态会自动恢复");
    });

  const startExport = () =>
    runAction("export", async () => {
      await api<Job>(`/api/batches/${batchId}/export`, { method: "POST" });
      await load(true);
      message.info("正在生成导出文件");
    });

  const downloadResult = (path: string, filename: string) => runAction("download", () => download(path, filename));

  const openSplit = (record: DeliveryException) => {
    setSplitTarget(record);
  };

  const selfOperated = batch?.workflow === "self_operated_inbound";
  const editor = useExceptionEditor({ splitTarget, setSplitTarget, review, selfOperated, runAction, load });

  const loadFailure = loadError && (
    <Alert
      type="error"
      showIcon
      title="读取批次失败"
      description={loadError}
      action={
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
          重试
        </Button>
      }
    />
  );

  if (!batch) {
    return (
      <div className="page-shell">
        <Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack} className="back-link">
          返回批次列表
        </Button>
        {loadFailure || <Card loading={loading} />}
      </div>
    );
  }

  const canEditFiles = ["draft", "preflight_ready", "failed"].includes(batch.status);
  const canAdoptCurrentSupplier = Boolean(
    canRefreshSupplierVersion &&
    batch.status === "draft" &&
    activeSupplierVersion &&
    activeSupplierVersion.id !== batch.version_ids.supplier
  );
  const computed = batch.status === "succeeded" || batch.download_ready;
  const exportJob = batch.jobs?.export;
  const showFileActions = canEditFiles || files.some((file) => file.download_ready);
  const needsReview = computed && totals.manual_total > 0;
  const hasMultipleFiles = files.length > 1;
  const mergedDownloadReady = hasMultipleFiles && batch.merged_download_ready;
  const needsMergedGeneration = batch.download_ready && hasMultipleFiles && !mergedDownloadReady;
  const currentStep = computed
    ? needsReview
      ? 3
      : 4
    : batch.status === "queued" || batch.status === "running"
      ? 2
      : batch.status === "preflight_ready"
        ? 1
        : 0;

  const workflowItems = [
    {
      title: "准备文件",
      content: selfOperated
        ? `${files.length} 份质检单 + ${batch.inbound_file?.uploaded ? 1 : 0} 份待入库数据`
        : files.length
          ? `${files.length} 个文件`
          : "等待上传"
    },
    { title: "预检", content: currentStep > 1 || batch.status === "preflight_ready" ? "检查通过" : "检查格式与供应商" },
    { title: "计算结果", content: computed ? "计算完成" : activeJob?.kind === "compute" ? "后台处理中" : "等待计算" },
    { title: "异常审校", content: computed ? `${totals.manual_total} 待处理` : "计算后开始" },
    { title: "导出下载", content: batch.download_ready ? "文件已生成" : "等待生成" }
  ];

  const focusReview = () => {
    reviewSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    reviewSection.current?.focus({ preventScroll: true });
  };

  return (
    <div className="page-shell batch-workbench">
      {loadFailure}
      <div className="batch-heading">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack} className="back-link">
            返回批次列表
          </Button>
          <div className="batch-title-row">
            <Typography.Title level={2}>{batch.name}</Typography.Title>
            <StatusTag status={batch.status} />
          </div>
          <Typography.Text type="secondary">
            批次 #{batch.id} · 更新于 {formatBeijingDateTime(batch.updated_at)}
          </Typography.Text>
        </div>
        <Space wrap className="batch-primary-actions">
          {canEditFiles && (
            <Upload accept=".xls,.xlsx" multiple showUploadList={false} customRequest={uploadFile}>
              <Button icon={<CloudUploadOutlined />} loading={action === "upload"}>
                {selfOperated ? "上传质检交货单" : "上传交货文件"}
              </Button>
            </Upload>
          )}
          {canEditFiles && selfOperated && (
            <Upload accept=".xls,.xlsx" showUploadList={false} customRequest={uploadInboundFile}>
              <Button icon={<CloudUploadOutlined />} loading={action === "upload-inbound"}>
                上传自营仓入库单
              </Button>
            </Upload>
          )}
          {(batch.status === "draft" || batch.status === "failed") && (
            <Button
              icon={<SafetyCertificateOutlined />}
              disabled={!files.length || (selfOperated && !batch.inbound_file?.uploaded)}
              loading={action === "preflight"}
              onClick={() => void preflight()}
            >
              执行预检
            </Button>
          )}
          {(batch.status === "preflight_ready" || batch.status === "failed") && (
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={action === "compute"}
              onClick={() => void compute()}
            >
              {batch.status === "failed" ? "重新计算" : "启动计算"}
            </Button>
          )}
          {activeJob && (
            <span className="job-indicator">
              <Spin size="small" /> {activeJob.kind === "compute" ? "正在计算" : "正在导出"}
            </span>
          )}
        </Space>
      </div>

      <div className="workflow-surface">
        <Steps
          current={currentStep}
          status={batch.status === "failed" ? "error" : "process"}
          responsive={false}
          items={workflowItems}
        />
      </div>

      {computed && (
        <section className="stage-actions" aria-labelledby="current-stage-title">
          <div className="stage-actions-copy">
            <strong id="current-stage-title">{needsReview ? `待处理 ${totals.manual_total} 件` : "结果可下载"}</strong>
            <span>{needsReview ? "处理完成后生成最终结果。" : "可生成或下载结果文件。"}</span>
          </div>
          {needsReview && (
            <Button aria-label="处理异常" type="primary" size="large" onClick={focusReview}>
              处理异常
            </Button>
          )}
          <div className="stage-actions-export">
            <div className="export-action-buttons">
              {batch.download_ready && !needsMergedGeneration ? (
                hasMultipleFiles ? (
                  <>
                    <Button
                      type={needsReview ? "default" : "primary"}
                      icon={<DownloadOutlined />}
                      onClick={() =>
                        void downloadResult(
                          `/api/batches/${batch.id}/download-merged`,
                          `${batch.name}_${selfOperated ? "合并积加入库" : "合并处理"}.xlsx`
                        )
                      }
                    >
                      下载合并结果
                    </Button>
                    <Button
                      icon={<DownloadOutlined />}
                      onClick={() =>
                        void downloadResult(`/api/batches/${batch.id}/download`, `${batch.name}_分文件.zip`)
                      }
                    >
                      下载分文件 ZIP
                    </Button>
                  </>
                ) : (
                  files[0]?.download_ready && (
                    <Button
                      type={needsReview ? "default" : "primary"}
                      icon={<DownloadOutlined />}
                      onClick={() =>
                        void downloadResult(
                          `/api/batch-files/${files[0].id}/download`,
                          `${files[0].original_name.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`
                        )
                      }
                    >
                      下载处理结果
                    </Button>
                  )
                )
              ) : (
                <Button
                  icon={<ExportOutlined />}
                  disabled={Boolean(activeJob)}
                  loading={action === "export" || activeJob?.kind === "export"}
                  onClick={() => void startExport()}
                >
                  {exportJob?.status === "stale" ? "重新生成导出" : needsMergedGeneration ? "生成合并结果" : "生成导出"}
                </Button>
              )}
            </div>
          </div>
        </section>
      )}

      {batch.error_message && (
        <Alert type="error" showIcon title="任务执行失败" description={batch.error_message} className="section-card" />
      )}

      <div className={`summary-strip ${computed ? "" : "summary-pending"}`}>
        <div className="summary-metric">
          <span>{selfOperated ? "质检合格总量" : "交货总量"}</span>
          <strong>{computed ? totals.delivery_total : "—"}</strong>
        </div>
        <div className="summary-metric import">
          <span>{selfOperated ? "可入库" : "可导入"}</span>
          <strong>{computed ? totals.import_total : "—"}</strong>
        </div>
        <div className="summary-metric pending">
          <span>待处理</span>
          <strong>{computed ? totals.manual_total : "—"}</strong>
        </div>
        <div className="summary-equation">
          <span>数量守恒</span>
          {computed ? (
            <strong className={totals.conserved ? "conservation-ok" : "conservation-bad"}>
              {totals.delivery_total} = {totals.import_total} + {totals.manual_total}
            </strong>
          ) : (
            <strong>尚未计算</strong>
          )}
        </div>
      </div>

      <Card
        title={selfOperated ? "本批次业务文件" : "来源文件与处理顺序"}
        className="section-card file-order-card"
        extra={
          <span className="order-hint">
            {selfOperated ? "序号越小，越先扣减待入库余额和超收额度" : "序号越小，越先扣减采购余额"}
          </span>
        }
      >
        {selfOperated && (
          <Alert
            className="inline-alert"
            type={batch.inbound_file?.uploaded ? "success" : "warning"}
            showIcon
            title={
              batch.inbound_file?.uploaded
                ? `自营仓入库单：${batch.inbound_file.original_name}`
                : "尚未上传自营仓入库单"
            }
            description="提供交货单、PO、SKU、站点和应收货数据；每个批次一份。"
          />
        )}
        {canEditFiles && files.length > 1 && (
          <Alert
            className="inline-alert"
            type="info"
            showIcon
            title={
              selfOperated
                ? "调整顺序会改变各质检单获得的待入库余额和超收额度；修改后必须重新预检。"
                : "调整顺序会改变各来源文件获得的采购余额；修改后必须重新预检。"
            }
          />
        )}
        <Table<BatchFile>
          rowKey="id"
          loading={loading}
          dataSource={files}
          pagination={false}
          scroll={{ x: 900 }}
          locale={{
            emptyText: (
              <Empty description={selfOperated ? "请先上传一份或多份质检交货单" : "请先上传一个或多个交货 Excel"} />
            )
          }}
          columns={[
            {
              title: "顺序",
              dataIndex: "file_order",
              width: 80,
              render: (value: number) => <span className="file-order">{String(value).padStart(2, "0")}</span>
            },
            { title: "来源文件", dataIndex: "original_name", ellipsis: true },
            {
              title: "供应商",
              dataIndex: "supplier_name",
              width: 150,
              render: (value: string) => value || <span className="muted">预检后识别</span>
            },
            {
              title: "交货",
              dataIndex: "delivery_total",
              width: 90,
              render: (value: number) => (computed ? value : "—")
            },
            {
              title: "可导入",
              dataIndex: "import_total",
              width: 90,
              render: (value: number) => (computed ? <span className="import-value">{value}</span> : "—")
            },
            {
              title: "待处理",
              dataIndex: "manual_total",
              width: 100,
              render: (value: number) =>
                computed ? <span className={value ? "pending-value" : ""}>{value}</span> : "—"
            },
            ...(showFileActions
              ? [
                  {
                    title: "操作",
                    width: canEditFiles ? 250 : 170,
                    fixed: "right" as const,
                    render: (_: unknown, file: BatchFile, index: number) => (
                      <Space>
                        {canEditFiles && (
                          <>
                            <Tooltip title={selfOperated ? "上移，提前扣减待入库余额" : "上移，提前扣减采购余额"}>
                              <Button
                                aria-label={`上移 ${file.original_name}`}
                                size="small"
                                icon={<ArrowUpOutlined />}
                                disabled={index === 0}
                                onClick={() => void move(file.id, -1)}
                              />
                            </Tooltip>
                            <Tooltip title={selfOperated ? "下移，延后扣减待入库余额" : "下移，延后扣减采购余额"}>
                              <Button
                                aria-label={`下移 ${file.original_name}`}
                                size="small"
                                icon={<ArrowDownOutlined />}
                                disabled={index === files.length - 1}
                                onClick={() => void move(file.id, 1)}
                              />
                            </Tooltip>
                            <Popconfirm
                              title="删除此交货文件？"
                              description="其余文件会自动重新编号。"
                              onConfirm={() => void removeFile(file)}
                            >
                              <Tooltip title="删除错传文件">
                                <Button
                                  aria-label={`删除 ${file.original_name}`}
                                  danger
                                  size="small"
                                  icon={<DeleteOutlined />}
                                />
                              </Tooltip>
                            </Popconfirm>
                          </>
                        )}
                        {file.download_ready && (
                          <Button
                            aria-label="下载单文件结果"
                            size="small"
                            icon={<DownloadOutlined />}
                            onClick={() =>
                              void downloadResult(
                                `/api/batch-files/${file.id}/download`,
                                `${file.original_name.replace(/\.(xls|xlsx)$/i, "")}_${selfOperated ? "积加入库" : "交货处理"}.xlsx`
                              )
                            }
                          >
                            下载单文件结果
                          </Button>
                        )}
                      </Space>
                    )
                  }
                ]
              : [])
          ]}
        />
      </Card>

      <Card
        title={
          <span className="locked-data-title">
            <LockOutlined /> 批次锁定版本
          </span>
        }
        className={`section-card compact-card locked-data-card ${lockedDataOpen ? "" : "is-collapsed"}`}
        extra={
          <Space size="small">
            {canAdoptCurrentSupplier && (
              <Button
                size="small"
                loading={action === "refresh-supplier-version"}
                onClick={() => void refreshSupplierVersion()}
              >
                采用当前供应商资料
              </Button>
            )}
            <Button
              type="link"
              size="small"
              aria-expanded={lockedDataOpen}
              onClick={() => setLockedDataOpen((open) => !open)}
            >
              {lockedDataOpen ? "收起锁定版本" : "查看锁定版本"}
            </Button>
          </Space>
        }
      >
        {lockedDataOpen && (
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 6 }}>
            {Object.entries(batch.versions ?? {}).map(([kind, version]) => (
              <Descriptions.Item key={kind} label={VERSION_LABELS[kind] ?? kind}>
                <Tooltip title={version.original_name}>{version.name}</Tooltip>
              </Descriptions.Item>
            ))}
            <Descriptions.Item label="超收规则">
              {selfOperated ? (
                batch.self_operated_overreceipt_rule ? (
                  <span className="locked-overreceipt-rule">
                    <strong>{batch.self_operated_overreceipt_rule.name}</strong>
                    <small>每个供应商 + SKU + 站点共享 +{batch.self_operated_overreceipt_rule.allowance}</small>
                  </span>
                ) : (
                  "未启用（不自动超收）"
                )
              ) : batch.overreceipt_rule ? (
                <span className="locked-overreceipt-rule">
                  <strong>{batch.overreceipt_rule.name}</strong>
                  <small>
                    短尾 +{batch.overreceipt_rule.short_tail_limit} / 中尾 +{batch.overreceipt_rule.medium_tail_limit} /
                    长尾 +{batch.overreceipt_rule.long_tail_limit}
                  </small>
                </span>
              ) : (
                "未启用（不自动超收）"
              )}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>

      {computed && (
        <ExceptionReviewTable
          review={review}
          fileById={fileById}
          hasOverreceiptRule={Boolean(selfOperated ? batch.self_operated_overreceipt_rule : batch.overreceipt_rule)}
          onOpen={openSplit}
          onReset={() => setSplitTarget(null)}
          sectionRef={reviewSection}
        />
      )}

      <ExceptionReviewDrawer editor={editor} batch={batch} fileById={fileById} action={action} />
    </div>
  );
}
