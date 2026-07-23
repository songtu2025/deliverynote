import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Spin,
  Steps,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message
} from "antd";
import type { UploadProps } from "antd";
import {
  AimOutlined,
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowUpOutlined,
  CheckCircleFilled,
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ExportOutlined,
  LockOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  SearchOutlined
} from "@ant-design/icons";

import { api, download } from "../api";
import { formatBeijingDateTime } from "../dateTime";
import type {
  Batch,
  BatchFile,
  DeliveryException,
  Job,
  SplitPart
} from "../types";
import { StatusTag } from "./BatchesPage";

const VERSION_LABELS: Record<string, string> = {
  purchase: "采购需求",
  product: "商品信息",
  supplier: "供应商资料",
  position: "库位/排仓",
  template: "导出模板"
};

const EXCEPTION_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: "未处理", color: "warning" },
  partial: { label: "部分处理", color: "processing" },
  resolved: { label: "已处理", color: "success" }
};

type SplitFormValues = { parts: SplitPart[] };

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function isActiveJob(job: Job | undefined): job is Job {
  return Boolean(job && (job.status === "queued" || job.status === "running"));
}

function ExceptionStatusTag({ status }: { status: string }) {
  const item = EXCEPTION_STATUS[status] ?? { label: status, color: "default" };
  return <Tag color={item.color}>{item.label}</Tag>;
}

function formatPositionValue(value: string | number): string {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  if (!text.startsWith("{")) return text;
  try {
    const mapping = JSON.parse(text) as Record<string, unknown>;
    if (!mapping || Array.isArray(mapping) || typeof mapping !== "object") return text;
    return Object.entries(mapping)
      .map(([msku, item]) => `${msku}：${String(item ?? "").trim() || "—"}`)
      .join("；");
  } catch {
    return text;
  }
}

function positionFilterValues(value: string | number): string[] {
  const text = String(value ?? "").trim();
  if (!text) return [];
  if (!text.startsWith("{")) return [text];
  try {
    const mapping = JSON.parse(text) as Record<string, unknown>;
    if (!mapping || Array.isArray(mapping) || typeof mapping !== "object") return [text];
    return Array.from(new Set(
      Object.values(mapping)
        .map((item) => String(item ?? "").trim())
        .filter(Boolean)
    ));
  } catch {
    return [text];
  }
}

function filterOptions(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)))
    .sort((left, right) => left.localeCompare(right, "zh-CN"))
    .map((value) => ({ value, label: value }));
}

function PositionValue({ value }: { value: string | number }) {
  const display = formatPositionValue(value);
  return (
    <Tooltip title={display === "—" ? "未匹配到当前批次锁定的库位资料" : display}>
      <span className={display === "—" ? "muted" : "position-reference-value"}>{display}</span>
    </Tooltip>
  );
}

export default function BatchDetail({ batchId, onBack }: { batchId: number; onBack: () => void }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [exceptions, setExceptions] = useState<DeliveryException[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [splitTarget, setSplitTarget] = useState<DeliveryException | null>(null);
  const [query, setQuery] = useState("");
  const [siteFilter, setSiteFilter] = useState<string>();
  const [scaleFilter, setScaleFilter] = useState<string>();
  const [stockingFilter, setStockingFilter] = useState<string>();
  const [statusFilter, setStatusFilter] = useState<string>();
  const [reasonFilter, setReasonFilter] = useState<string>();
  const [splitForm] = Form.useForm<SplitFormValues>();
  const splitParts = Form.useWatch("parts", splitForm) ?? [];
  const pollingJob = useRef<number | null>(null);
  const announcedJobs = useRef(new Set<number>());
  const reviewSection = useRef<HTMLDivElement | null>(null);

  const load = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [batchResult, exceptionRows] = await Promise.all([
        api<Batch>(`/api/batches/${batchId}`),
        api<DeliveryException[]>(`/api/batches/${batchId}/exceptions`)
      ]);
      setBatch(batchResult);
      setExceptions(exceptionRows);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取批次失败");
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [batchId]);

  const activeJob = useMemo(() => {
    const jobs = batch?.jobs;
    if (isActiveJob(jobs?.compute)) return jobs.compute;
    if (isActiveJob(jobs?.export)) return jobs.export;
    return undefined;
  }, [batch?.jobs]);

  useEffect(() => {
    if (!activeJob || pollingJob.current === activeJob.id) return;
    let cancelled = false;
    pollingJob.current = activeJob.id;

    const poll = async () => {
      try {
        const job = await api<Job>(`/api/jobs/${activeJob.id}`);
        if (cancelled) return;
        if (job.status === "succeeded" || job.status === "failed") {
          pollingJob.current = null;
          await load(true);
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
        if (!cancelled) {
          message.error(error instanceof Error ? error.message : "读取任务状态失败");
        }
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (pollingJob.current === activeJob.id) pollingJob.current = null;
    };
  }, [activeJob?.id, activeJob?.status]);

  const totals = useMemo(() => batch?.summary ?? {
    delivery_total: 0,
    import_total: 0,
    manual_total: 0,
    conserved: true
  }, [batch]);

  const files = batch?.files ?? [];
  const fileById = useMemo(
    () => Object.fromEntries(files.map((file) => [file.id, file])),
    [files]
  );
  const reasonOptions = useMemo(
    () => Array.from(new Set(exceptions.map((item) => item.reason))).map((reason) => ({ value: reason, label: reason })),
    [exceptions]
  );
  const siteOptions = useMemo(
    () => filterOptions(exceptions.map((item) => item.full_site)),
    [exceptions]
  );
  const scaleOptions = useMemo(
    () => filterOptions(exceptions.flatMap((item) => positionFilterValues(item.scale_position))),
    [exceptions]
  );
  const stockingOptions = useMemo(
    () => filterOptions(exceptions.flatMap((item) => positionFilterValues(item.stocking_position))),
    [exceptions]
  );
  const filteredExceptions = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase("zh-CN");
    return exceptions.filter((item) => {
      const source = fileById[item.batch_file_id]?.original_name ?? "";
      const haystack = [
        source,
        item.sku,
        item.full_site,
        item.destination,
        formatPositionValue(item.scale_position),
        formatPositionValue(item.stocking_position),
        formatPositionValue(item.ordered_days)
      ].join(" ").toLocaleLowerCase("zh-CN");
      return (!keyword || haystack.includes(keyword))
        && (!siteFilter || item.full_site === siteFilter)
        && (!scaleFilter || positionFilterValues(item.scale_position).includes(scaleFilter))
        && (!stockingFilter || positionFilterValues(item.stocking_position).includes(stockingFilter))
        && (!statusFilter || item.status === statusFilter)
        && (!reasonFilter || item.reason === reasonFilter);
    });
  }, [exceptions, fileById, query, reasonFilter, scaleFilter, siteFilter, statusFilter, stockingFilter]);

  const runAction = async (name: string, operation: () => Promise<void>) => {
    setAction(name);
    try {
      await operation();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "操作失败");
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
      message.success("交货文件已上传，预检状态已更新");
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

  const preflight = () => runAction("preflight", async () => {
    await api<Batch>(`/api/batches/${batchId}/preflight`, { method: "POST" });
    await load(true);
    message.success("所有基础资料和交货文件均已通过预检");
  });

  const compute = () => runAction("compute", async () => {
    await api<Job>(`/api/batches/${batchId}/compute`, { method: "POST" });
    await load(true);
    message.info("计算任务已提交，可以离开页面，返回后状态会自动恢复");
  });

  const startExport = () => runAction("export", async () => {
    await api<Job>(`/api/batches/${batchId}/export`, { method: "POST" });
    await load(true);
    message.info("正在生成导出文件");
  });

  const openSplit = (record: DeliveryException) => {
    setSplitTarget(record);
    splitForm.setFieldsValue({
      parts: record.parts.length
        ? record.parts
        : [
            {
              quantity: record.manual_quantity,
              destination: record.destination,
              site: record.full_site.includes("、") ? "" : record.full_site,
              supplier_code: "",
              sku: record.sku,
              delivery_note: record.reason,
              resolved: false
            }
          ]
    });
  };

  const splitTotal = splitParts.reduce((sum, part) => sum + Number(part?.quantity ?? 0), 0);
  const splitRemaining = (splitTarget?.manual_quantity ?? 0) - splitTotal;
  const splitValid = Boolean(
    splitTarget
    && splitParts.length
    && splitRemaining === 0
    && splitParts.every((part) => Number(part?.quantity ?? 0) > 0)
  );

  const saveSplit = async () => {
    if (!splitTarget || !splitValid) return;
    const values = await splitForm.validateFields();
    await runAction("split", async () => {
      await api<DeliveryException>(`/api/exceptions/${splitTarget.id}/split`, {
        method: "PUT",
        body: JSON.stringify(values)
      });
      setSplitTarget(null);
      splitForm.resetFields();
      await load(true);
      message.success("拆分已保存，批次数量保持守恒");
    });
  };

  if (!batch) {
    return <Card loading={loading} />;
  }

  const canEditFiles = ["draft", "preflight_ready", "failed"].includes(batch.status);
  const computed = batch.status === "succeeded" || batch.download_ready;
  const exportJob = batch.jobs?.export;
  const showFileActions = canEditFiles || files.some((file) => file.download_ready);
  const needsReview = computed && totals.manual_total > 0;
  const hasMultipleFiles = files.length > 1;
  const mergedDownloadReady = hasMultipleFiles && batch.merged_download_ready;
  const needsMergedGeneration = (
    batch.download_ready
    && hasMultipleFiles
    && !mergedDownloadReady
  );
  const currentStep = computed
    ? needsReview ? 3 : 4
      : batch.status === "queued" || batch.status === "running"
        ? 2
        : batch.status === "preflight_ready"
          ? 1
          : 0;

  const workflowItems = [
    { title: "准备文件", content: files.length ? `${files.length} 个文件` : "等待上传" },
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
      <div className="batch-heading">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={onBack} className="back-link">
            返回批次列表
          </Button>
          <div className="batch-title-row">
            <Typography.Title level={2}>{batch.name}</Typography.Title>
            <StatusTag status={batch.status} />
          </div>
          <Typography.Text type="secondary">批次 #{batch.id} · 更新于 {formatBeijingDateTime(batch.updated_at)}</Typography.Text>
        </div>
        <Space wrap className="batch-primary-actions">
          {canEditFiles && (
            <Upload accept=".xls,.xlsx" multiple showUploadList={false} customRequest={uploadFile}>
              <Button icon={<CloudUploadOutlined />} loading={action === "upload"}>上传交货文件</Button>
            </Upload>
          )}
          {(batch.status === "draft" || batch.status === "failed") && (
            <Button
              icon={<SafetyCertificateOutlined />}
              disabled={!files.length}
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
          {activeJob && <span className="job-indicator"><Spin size="small" /> {activeJob.kind === "compute" ? "正在计算" : "正在导出"}</span>}
        </Space>
      </div>

      <div className="workflow-surface">
        <Steps current={currentStep} status={batch.status === "failed" ? "error" : "process"} responsive={false} items={workflowItems} />
      </div>

      {computed && (
        <section
          className={`stage-guidance ${needsReview ? "" : "stage-guidance-results"}`}
          aria-labelledby="current-stage-title"
        >
          <AimOutlined className="stage-guidance-icon" />
          <div className="stage-guidance-copy">
            <strong id="current-stage-title">
              当前阶段：{needsReview ? "异常审校" : "导出下载"}
            </strong>
            <span>
              {needsReview
                ? `发现 ${totals.manual_total} 件超出规则或需要判断的记录，请先完成拆分审校。`
                : "计算结果已确认，可直接生成或下载处理结果。"}
            </span>
          </div>
          {needsReview && (
            <div className="stage-guidance-primary">
              <span>下一步（唯一主操作）</span>
              <Button aria-label={`拆分审校（${totals.manual_total}）`} type="primary" size="large" onClick={focusReview}>
                拆分审校（{totals.manual_total}）<RightOutlined />
              </Button>
            </div>
          )}
          <div className="stage-guidance-secondary">
            <span>{batch.download_ready && !needsMergedGeneration ? "下载处理结果" : "生成处理结果"}</span>
            <div className="export-action-buttons">
              {batch.download_ready && !needsMergedGeneration ? (
                hasMultipleFiles ? (
                  <>
                    <Button
                      type={needsReview ? "default" : "primary"}
                      icon={<DownloadOutlined />}
                      onClick={() => void download(
                        `/api/batches/${batch.id}/download-merged`,
                        `${batch.name}_合并处理.xlsx`
                      )}
                    >
                      下载合并结果
                    </Button>
                    <Button
                      icon={<DownloadOutlined />}
                      onClick={() => void download(
                        `/api/batches/${batch.id}/download`,
                        `${batch.name}_分文件.zip`
                      )}
                    >
                      下载分文件 ZIP
                    </Button>
                  </>
                ) : (
                  files[0]?.download_ready && (
                    <Button
                      type={needsReview ? "default" : "primary"}
                      icon={<DownloadOutlined />}
                      onClick={() => void download(
                        `/api/batch-files/${files[0].id}/download`,
                        `${files[0].original_name.replace(/\.(xls|xlsx)$/i, "")}_交货处理.xlsx`
                      )}
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
                  {exportJob?.status === "stale"
                    ? "重新生成导出"
                    : needsMergedGeneration
                      ? "生成合并结果"
                      : "生成导出"}
                </Button>
              )}
            </div>
            <small>
              {hasMultipleFiles
                ? batch.download_ready && !needsMergedGeneration
                  ? "合并 Excel 按来源顺序汇总；ZIP 保留每张交货单的独立文件。"
                  : "将同时生成合并 Excel 和分文件 ZIP；待处理记录仍保留在待处理工作表。"
                : "单个来源直接下载对应处理结果；待处理记录仍保留在待处理工作表。"}
            </small>
          </div>
        </section>
      )}

      {batch.error_message && (
        <Alert
          type="error"
          showIcon
          title="任务执行失败"
          description={batch.error_message}
          className="section-card"
        />
      )}

      <div className={`summary-strip ${computed ? "" : "summary-pending"}`}>
        <div className="summary-metric"><span>交货总量</span><strong>{computed ? totals.delivery_total : "—"}</strong></div>
        <div className="summary-metric import"><span>可导入</span><strong>{computed ? totals.import_total : "—"}</strong></div>
        <div className="summary-metric pending"><span>待处理</span><strong>{computed ? totals.manual_total : "—"}</strong></div>
        <div className="summary-equation">
          <span>数量守恒</span>
          {computed ? (
            <strong className={totals.conserved ? "conservation-ok" : "conservation-bad"}>
              {totals.delivery_total} = {totals.import_total} + {totals.manual_total}
            </strong>
          ) : <strong>尚未计算</strong>}
        </div>
      </div>

      <Card
        title="来源文件与处理顺序"
        className="section-card file-order-card"
        extra={<span className="order-hint">序号越小，越先扣减采购余额</span>}
      >
        {canEditFiles && files.length > 1 && (
          <Alert
            className="inline-alert"
            type="info"
            showIcon
            title="调整顺序会改变各来源文件获得的采购余额；修改后必须重新预检。"
          />
        )}
        <Table<BatchFile>
          rowKey="id"
          loading={loading}
          dataSource={files}
          pagination={false}
          scroll={{ x: 900 }}
          locale={{ emptyText: <Empty description="请先上传一个或多个交货 Excel" /> }}
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
              render: (value: number) => computed ? value : "—"
            },
            {
              title: "可导入",
              dataIndex: "import_total",
              width: 90,
              render: (value: number) => computed ? <span className="import-value">{value}</span> : "—"
            },
            {
              title: "待处理",
              dataIndex: "manual_total",
              width: 100,
              render: (value: number) => computed ? <span className={value ? "pending-value" : ""}>{value}</span> : "—"
            },
            ...(showFileActions ? [{
              title: "操作",
              width: canEditFiles ? 210 : 130,
              fixed: "right" as const,
              render: (_: unknown, file: BatchFile, index: number) => (
                <Space>
                  {canEditFiles && (
                    <>
                      <Tooltip title="上移，提前扣减采购余额">
                        <Button aria-label={`上移 ${file.original_name}`} size="small" icon={<ArrowUpOutlined />} disabled={index === 0} onClick={() => void move(file.id, -1)} />
                      </Tooltip>
                      <Tooltip title="下移，延后扣减采购余额">
                        <Button aria-label={`下移 ${file.original_name}`} size="small" icon={<ArrowDownOutlined />} disabled={index === files.length - 1} onClick={() => void move(file.id, 1)} />
                      </Tooltip>
                      <Popconfirm title="删除此交货文件？" description="其余文件会自动重新编号。" onConfirm={() => void removeFile(file)}>
                        <Tooltip title="删除错传文件">
                          <Button aria-label={`删除 ${file.original_name}`} danger size="small" icon={<DeleteOutlined />} />
                        </Tooltip>
                      </Popconfirm>
                    </>
                  )}
                  {file.download_ready && (
                    <Button
                      size="small"
                      icon={<DownloadOutlined />}
                      onClick={() => void download(`/api/batch-files/${file.id}/download`, `${file.original_name.replace(/\.(xls|xlsx)$/i, "")}_交货处理.xlsx`)}
                    >
                      下载
                    </Button>
                  )}
                </Space>
              )
            }] : [])
          ]}
        />
      </Card>

      <Card
        title={<span className="locked-data-title"><LockOutlined /> 本批次锁定的基础资料与规则（不可修改）</span>}
        className="section-card compact-card locked-data-card"
      >
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 6 }}>
          {Object.entries(batch.versions ?? {}).map(([kind, version]) => (
            <Descriptions.Item key={kind} label={VERSION_LABELS[kind] ?? kind}>
              <Tooltip title={version.original_name}>{version.name}</Tooltip>
            </Descriptions.Item>
          ))}
          <Descriptions.Item label="超收规则">
            {batch.overreceipt_rule ? (
              <span className="locked-overreceipt-rule">
                <strong>{batch.overreceipt_rule.name}</strong>
                <small>
                  短尾 +{batch.overreceipt_rule.short_tail_limit} / 中尾 +{batch.overreceipt_rule.medium_tail_limit} / 长尾 +{batch.overreceipt_rule.long_tail_limit}
                </small>
              </span>
            ) : "未启用（不自动超收）"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {computed && (
        <div ref={reviewSection} tabIndex={-1} className="review-section-anchor">
        <Card
          title={`待处理审校（共 ${exceptions.length} 条）`}
          extra={<span className="toolbar-count">当前显示 {filteredExceptions.length} 条</span>}
          className="section-card exception-review-card"
        >
          <div className="table-toolbar exception-toolbar">
            <div className="exception-filter-field exception-search-field">
              <label htmlFor="exception-search">搜索</label>
              <Input
                id="exception-search"
                aria-label="搜索待处理记录"
                allowClear
                prefix={<SearchOutlined />}
                placeholder="搜索来源、SKU、站点或目的仓"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="exception-filter-field">
              <label htmlFor="exception-site-filter">站点</label>
              <Select
                id="exception-site-filter"
                aria-label="站点筛选"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="全部站点"
                options={siteOptions}
                value={siteFilter}
                onChange={setSiteFilter}
              />
            </div>
            <div className="exception-filter-field">
              <label htmlFor="exception-scale-filter">规模定位</label>
              <Select
                id="exception-scale-filter"
                aria-label="规模定位筛选"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="全部规模定位"
                options={scaleOptions}
                value={scaleFilter}
                onChange={setScaleFilter}
              />
            </div>
            <div className="exception-filter-field">
              <label htmlFor="exception-stocking-filter">备货定位</label>
              <Select
                id="exception-stocking-filter"
                aria-label="备货定位筛选"
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="全部备货定位"
                options={stockingOptions}
                value={stockingFilter}
                onChange={setStockingFilter}
              />
            </div>
            <div className="exception-filter-field">
              <label htmlFor="exception-reason-filter">原因</label>
              <Select
                id="exception-reason-filter"
                aria-label="原因筛选"
                allowClear
                placeholder="全部原因"
                options={reasonOptions}
                value={reasonFilter}
                onChange={setReasonFilter}
              />
            </div>
            <div className="exception-filter-field exception-status-field">
              <label htmlFor="exception-status-filter">状态</label>
              <Select
                id="exception-status-filter"
                aria-label="状态筛选"
                allowClear
                placeholder="全部状态"
                options={Object.entries(EXCEPTION_STATUS).map(([value, item]) => ({ value, label: item.label }))}
                value={statusFilter}
                onChange={setStatusFilter}
              />
            </div>
          </div>
          <Table<DeliveryException>
            rowKey="id"
            dataSource={filteredExceptions}
            scroll={{ x: 1020 }}
            locale={{ emptyText: <Empty description={exceptions.length ? "没有匹配的待处理记录" : "本批次没有待处理记录"} /> }}
            columns={[
              {
                title: "来源文件",
                dataIndex: "batch_file_id",
                width: 170,
                ellipsis: true,
                render: (fileId: number) => fileById[fileId]?.original_name ?? `文件 #${fileId}`
              },
              { title: "SKU", dataIndex: "sku", width: 80 },
              { title: "站点", dataIndex: "full_site", width: 145, ellipsis: true },
              { title: "目的仓", dataIndex: "destination", width: 130, ellipsis: true },
              {
                title: "规模定位",
                dataIndex: "scale_position",
                width: 90,
                ellipsis: true,
                render: (value: string | number, record) => (
                  <Tooltip title={`备货定位：${formatPositionValue(record.stocking_position)}；已下单可售天数：${formatPositionValue(record.ordered_days)}`}>
                    <span><PositionValue value={value} /></span>
                  </Tooltip>
                )
              },
              {
                title: "待处理量",
                dataIndex: "manual_quantity",
                width: 85,
                render: (value: number) => <strong className="pending-value">{value}</strong>
              },
              { title: "原因", dataIndex: "reason", width: 140, ellipsis: true },
              {
                title: "状态",
                dataIndex: "status",
                width: 80,
                render: (value: string) => <ExceptionStatusTag status={value} />
              },
              {
                title: "操作",
                width: 100,
                fixed: "right",
                render: (_, record) => <Button type="link" onClick={() => openSplit(record)}>拆分审校</Button>
              }
            ]}
          />
        </Card>
        </div>
      )}

      <Drawer
        title={`拆分审校 · ${splitTarget?.sku ?? ""}`}
        size={520}
        open={splitTarget !== null}
        onClose={() => setSplitTarget(null)}
        extra={splitTarget ? <ExceptionStatusTag status={splitTarget.status} /> : null}
        footer={(
          <div className="drawer-footer">
            <Button onClick={() => setSplitTarget(null)}>取消</Button>
            <Tooltip title={splitValid ? "" : "拆分数量必须为正数，且合计必须等于原待处理量"}>
              <Button type="primary" disabled={!splitValid} loading={action === "split"} onClick={() => void saveSplit()}>
                保存拆分
              </Button>
            </Tooltip>
          </div>
        )}
      >
        {splitTarget && (
          <>
            <Descriptions className="split-source" size="small" column={1}>
              <Descriptions.Item label="来源文件">{fileById[splitTarget.batch_file_id]?.original_name}</Descriptions.Item>
              <Descriptions.Item label="站点">{splitTarget.full_site || "—"}</Descriptions.Item>
              <Descriptions.Item label="目的仓">{splitTarget.destination || "—"}</Descriptions.Item>
              <Descriptions.Item label="规模定位"><PositionValue value={splitTarget.scale_position} /></Descriptions.Item>
              <Descriptions.Item label="备货定位"><PositionValue value={splitTarget.stocking_position} /></Descriptions.Item>
              <Descriptions.Item label="已下单可售天数"><PositionValue value={splitTarget.ordered_days} /></Descriptions.Item>
              <Descriptions.Item label="异常原因"><Tag color="warning">{splitTarget.reason}</Tag></Descriptions.Item>
            </Descriptions>

            <div className={`split-conservation ${splitValid ? "valid" : "invalid"}`}>
              <div>
                <span>原待处理</span>
                <strong>{splitTarget.manual_quantity}</strong>
              </div>
              <div>
                <span>已拆分</span>
                <strong>{splitTotal}</strong>
              </div>
              <div>
                <span>剩余</span>
                <strong>{splitRemaining}</strong>
              </div>
              {splitValid && <CheckCircleFilled aria-label="数量守恒通过" />}
            </div>

            <Form form={splitForm} layout="vertical">
              <Form.List name="parts">
                {(fields, { add, remove }) => (
                  <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                    {fields.map((field, index) => (
                      <div className="split-part" key={field.key}>
                        <div className="split-part-heading">
                          <strong>拆分 {index + 1}</strong>
                          {fields.length > 1 && (
                            <Button danger type="link" size="small" onClick={() => remove(field.name)}>删除</Button>
                          )}
                        </div>
                        <div className="split-fields-row">
                          <Form.Item
                            name={[field.name, "quantity"]}
                            label="数量"
                            rules={[{ required: true, type: "number", min: 1, message: "数量必须大于 0" }]}
                          >
                            <InputNumber min={1} precision={0} style={{ width: 130 }} />
                          </Form.Item>
                          <Form.Item name={[field.name, "resolved"]} label="处理结果" valuePropName="checked">
                            <Switch checkedChildren="可正式导入" unCheckedChildren="继续待处理" />
                          </Form.Item>
                        </div>
                        <Form.Item
                          name={[field.name, "destination"]}
                          label="目的仓"
                          rules={[{
                            validator: (_, value) => splitForm.getFieldValue(["parts", field.name, "resolved"]) && !value
                              ? Promise.reject(new Error("可正式导入部分必须填写目的仓"))
                              : Promise.resolve()
                          }]}
                        >
                          <Input />
                        </Form.Item>
                        <Form.Item
                          name={[field.name, "site"]}
                          label="完整站点"
                          rules={[{
                            validator: (_, value) => splitForm.getFieldValue(["parts", field.name, "resolved"]) && !value
                              ? Promise.reject(new Error("可正式导入部分必须填写完整站点"))
                              : Promise.resolve()
                          }]}
                        >
                          <Input />
                        </Form.Item>
                        <div className="split-fields-row">
                          <Form.Item name={[field.name, "sku"]} label="SKU">
                            <Input />
                          </Form.Item>
                          <Form.Item name={[field.name, "supplier_code"]} label="供应商编码">
                            <Input placeholder="默认沿用来源文件" />
                          </Form.Item>
                        </div>
                        <Form.Item name={[field.name, "delivery_note"]} label="交货备注">
                          <Input />
                        </Form.Item>
                      </div>
                    ))}
                    <Button
                      block
                      type="dashed"
                      icon={<PlusOutlined />}
                      onClick={() => add({
                        quantity: splitRemaining > 0 ? splitRemaining : 1,
                        destination: splitTarget.destination,
                        site: splitTarget.full_site.includes("、") ? "" : splitTarget.full_site,
                        supplier_code: "",
                        sku: splitTarget.sku,
                        delivery_note: splitTarget.reason,
                        resolved: false
                      })}
                    >
                      增加拆分{splitRemaining > 0 ? `并填入剩余 ${splitRemaining}` : ""}
                    </Button>
                  </Space>
                )}
              </Form.List>
            </Form>
          </>
        )}
      </Drawer>
    </div>
  );
}
