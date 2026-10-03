import { useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Descriptions, Space, Spin, Steps, Tooltip, Typography, Upload } from "antd";
import {
  ArrowLeftOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  ExportOutlined,
  LockOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined
} from "@ant-design/icons";

import { formatBeijingDateTime } from "../dateTime";
import type { DeliveryException } from "../types";
import StatusTag from "../BatchStatusTag";
import BatchFileTable from "./batch-detail/BatchFileTable";
import { useBatchFiles } from "./batch-detail/useBatchFiles";
import { useBatchAction } from "./batch-detail/useBatchAction";
import ExceptionReviewTable from "./batch-detail/ExceptionReviewTable";
import ExceptionReviewDrawer from "./batch-detail/ExceptionReviewDrawer";
import { useExceptionEditor } from "./batch-detail/useExceptionEditor";
import { useBatchDetailData } from "./batch-detail/useBatchDetailData";
import { useBatchJob } from "./batch-detail/useBatchJob";
import { useBatchTasks } from "./batch-detail/useBatchTasks";

const VERSION_LABELS: Record<string, string> = {
  purchase: "采购需求",
  product: "商品信息",
  supplier: "供应商资料",
  position: "MSKU定位",
  template: "导出模板",
  inbound_template: "积加入库模板"
};

export default function BatchDetail({
  batchId,
  onBack,
  canRefreshSupplierVersion = false
}: {
  batchId: number;
  onBack: () => void;
  canRefreshSupplierVersion?: boolean;
}) {
  const { action, runAction } = useBatchAction();
  const [splitTarget, setSplitTarget] = useState<DeliveryException | null>(null);
  const [lockedDataOpen, setLockedDataOpen] = useState(true);
  const reviewSection = useRef<HTMLDivElement | null>(null);
  const data = useBatchDetailData(batchId, canRefreshSupplierVersion, setSplitTarget);
  const { batch, activeSupplierVersion, loading, loadError, review, load } = data;
  const activeJob = useBatchJob(batch, load);

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

  const selfOperated = batch?.workflow === "self_operated_inbound";
  const fileActions = useBatchFiles({ batchId, files, selfOperated, runAction, load });
  const { uploadFile, uploadInboundFile } = fileActions;

  const tasks = useBatchTasks(batchId, data, runAction);
  const { preflight, refreshSupplierVersion, compute, startExport, downloadResult } = tasks;

  const openSplit = (record: DeliveryException) => {
    setSplitTarget(record);
  };

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

      <BatchFileTable
        batch={batch}
        files={files}
        loading={loading}
        computed={computed}
        canEditFiles={canEditFiles}
        actions={fileActions}
        downloadResult={downloadResult}
      />

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
