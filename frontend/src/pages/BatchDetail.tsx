import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Button, Card } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import BatchBreadcrumb from "./batch-detail/BatchBreadcrumb";
import DeliveryDetailTabs from "./batch-detail/DeliveryDetailTabs";
import BatchOverview from "./batch-detail/BatchOverview";
import BatchSummary from "./batch-detail/BatchSummary";
import BatchLockedVersions from "./batch-detail/BatchLockedVersions";
import { batchPresentation } from "./batch-detail/batchPresentation";
import type { DeliveryException } from "../types";
import BatchFileTable from "./batch-detail/BatchFileTable";
import { useBatchFiles } from "./batch-detail/useBatchFiles";
import { useBatchAction } from "./batch-detail/useBatchAction";
import ExceptionReviewTable from "./batch-detail/ExceptionReviewTable";
import ExceptionReviewDrawer from "./batch-detail/ExceptionReviewDrawer";
import { useExceptionEditor } from "./batch-detail/useExceptionEditor";
import { useBatchDetailData } from "./batch-detail/useBatchDetailData";
import type { BatchDetailData } from "./batch-detail/useBatchDetailData";
import { useBatchJob } from "./batch-detail/useBatchJob";
import { useBatchTasks } from "./batch-detail/useBatchTasks";
import ReceiptReview from "./batch-detail/ReceiptReview";
import SelfOperatedDetailTabs from "./batch-detail/SelfOperatedDetailTabs";
import BatchPurchaseSnapshot, { BatchPurchaseSnapshotNotice } from "./batch-detail/BatchPurchaseSnapshot";

export default function BatchDetail({
  batchId,
  onBack,
  canRefreshSupplierVersion
}: {
  batchId: number;
  onBack: () => void;
  canRefreshSupplierVersion?: boolean;
}) {
  const { action, runAction } = useBatchAction();
  const [splitTarget, setSplitTarget] = useState<DeliveryException | null>(null);
  const reviewSection = useRef<HTMLDivElement | null>(null);
  const [detailTabs, setDetailTabs] = useState<Record<number, string>>({});
  const [reviewFocusRequested, setReviewFocusRequested] = useState(false);
  const [materialsOpen, setMaterialsOpen] = useState(false);
  const data = useBatchDetailData(batchId, Boolean(canRefreshSupplierVersion), setSplitTarget);
  const { batch, activeSupplierVersion, loading, loadError, review, load } = data;
  const activeJob = useBatchJob(batch, load);

  const files = useMemo(() => batch?.files ?? [], [batch?.files]);
  const fileById = useMemo(() => Object.fromEntries(files.map((file) => [file.id, file])), [files]);

  const selfOperated = batch?.workflow === "self_operated_inbound";
  const fileActions = useBatchFiles({ batchId, files, selfOperated, runAction, load });

  const tasks = useBatchTasks(batchId, data, runAction);
  const { refreshSupplierVersion, downloadResult } = tasks;

  const openSplit = (record: DeliveryException) => {
    setSplitTarget(record);
  };

  const editor = useExceptionEditor({ splitTarget, setSplitTarget, review, runAction, load });

  useEffect(() => {
    if (!reviewFocusRequested || !reviewSection.current) return;
    reviewSection.current.scrollIntoView({ behavior: "smooth", block: "start" });
    reviewSection.current.focus({ preventScroll: true });
    setReviewFocusRequested(false);
  }, [reviewFocusRequested, detailTabs]);

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
        <BatchBreadcrumb batchId={batchId} onBack={onBack} />
        {loadFailure || <Card loading={loading} />}
      </div>
    );
  }

  const { canEditFiles, computed } = batchPresentation(batch);
  const selectDetailTab = (key: string) => setDetailTabs((current) => ({ ...current, [batchId]: key }));

  const focusReview = () => {
    selectDetailTab("review");
    setReviewFocusRequested(true);
  };

  const taskContent = (
    <>
      <BatchOverview
        batch={batch}
        activeJob={activeJob}
        action={action}
        fileActions={fileActions}
        tasks={tasks}
        focusReview={focusReview}
        reviewStats={availableReviewStats(data)}
        reviewError={Boolean(loadError)}
        extra={selfOperated && <Button onClick={() => setMaterialsOpen(true)}>批次资料</Button>}
      />

      <BatchErrorNotice batch={batch} />

      <BatchSummary batch={batch} />
    </>
  );

  const fileContent = (
    <BatchFileTable
      batch={batch}
      files={files}
      loading={loading}
      computed={computed}
      canEditFiles={canEditFiles}
      actions={fileActions}
      downloadResult={downloadResult}
    />
  );
  const versionContent = (
    <BatchLockedVersions
      batch={batch}
      activeSupplierVersion={activeSupplierVersion}
      canRefreshSupplierVersion={Boolean(canRefreshSupplierVersion)}
      action={action}
      refreshSupplierVersion={refreshSupplierVersion}
    />
  );
  const reviewContent = computed && (
    <>
      <BatchPurchaseSnapshotNotice />
      <ExceptionReviewTable
        selfOperated={selfOperated}
        review={review}
        fileById={fileById}
        hasOverreceiptRule={Boolean(selfOperated ? batch.self_operated_overreceipt_rule : batch.overreceipt_rule)}
        onOpen={openSplit}
        onReset={() => setSplitTarget(null)}
        sectionRef={reviewSection}
      />
    </>
  );

  return (
    <BatchPurchaseSnapshot batch={batch}>
      <BatchWorkbench
        notice={loadFailure}
        breadcrumb={<BatchBreadcrumb batchId={batchId} selfOperated={selfOperated} onBack={onBack} />}
        taskContent={taskContent}
      >
        {selfOperated ? (
          <SelfOperatedDetailTabs
            batch={batch}
            activeKey={detailTabs[batchId]}
            onChange={selectDetailTab}
            reviewStats={availableReviewStats(data)}
            reviewState={review}
            onReset={() => setSplitTarget(null)}
            materialsOpen={materialsOpen}
            onCloseMaterials={() => setMaterialsOpen(false)}
            files={fileContent}
            versions={versionContent}
            receipts={<ReceiptReview batch={batch} runAction={runAction} load={load} />}
            review={reviewContent}
          />
        ) : (
          <DeliveryDetailTabs
            computed={computed}
            activeKey={detailTabs[batchId]}
            onChange={selectDetailTab}
            reviewStats={availableReviewStats(data)}
            fileCount={files.length}
            files={fileContent}
            versions={versionContent}
            review={reviewContent}
          />
        )}

        <ExceptionReviewDrawer editor={editor} batch={batch} fileById={fileById} action={action} />
      </BatchWorkbench>
    </BatchPurchaseSnapshot>
  );
}

function availableReviewStats(data: BatchDetailData) {
  const available =
    data.batch?.workflow === "self_operated_inbound" ? data.review.hasLoadedExceptions : !data.review.exceptionsLoading;
  return available && !data.loadError ? data.review.reviewStats : undefined;
}

function BatchWorkbench({
  notice,
  breadcrumb,
  taskContent,
  children
}: {
  notice: ReactNode;
  breadcrumb: ReactNode;
  taskContent: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="page-shell batch-workbench batch-detail--compact">
      {notice}
      {breadcrumb}
      <section className="batch-task-surface" aria-label="当前批次任务">
        {taskContent}
      </section>
      {children}
    </div>
  );
}

function BatchErrorNotice({ batch }: { batch: import("../types").Batch }) {
  if (!batch.error_message) return null;
  return (
    <Alert
      type="error"
      showIcon
      title={batch.receipt?.issue_count ? "累计实收待核对" : "任务执行失败"}
      description={batch.error_message}
      className="section-card"
    />
  );
}
