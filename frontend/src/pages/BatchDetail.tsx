import { useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Alert, Button, Card } from "antd";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import BatchOverview from "./batch-detail/BatchOverview";
import BatchExportActions from "./batch-detail/BatchExportActions";
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
import { useBatchJob } from "./batch-detail/useBatchJob";
import { useBatchTasks } from "./batch-detail/useBatchTasks";

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

  const { canEditFiles, computed } = batchPresentation(batch);

  const focusReview = () => {
    reviewSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    reviewSection.current?.focus({ preventScroll: true });
  };

  const taskContent = (
    <>
      <BatchOverview
        batch={batch}
        activeJob={activeJob}
        action={action}
        fileActions={fileActions}
        tasks={tasks}
        onBack={onBack}
      />
      {computed && (
        <BatchExportActions
          batch={batch}
          activeJob={activeJob}
          action={action}
          tasks={tasks}
          focusReview={focusReview}
        />
      )}

      {batch.error_message && (
        <Alert type="error" showIcon title="任务执行失败" description={batch.error_message} className="section-card" />
      )}

      <BatchSummary batch={batch} />
    </>
  );

  return (
    <BatchWorkbench selfOperated={selfOperated} notice={loadFailure} taskContent={taskContent}>
      <BatchFileTable
        batch={batch}
        files={files}
        loading={loading}
        computed={computed}
        canEditFiles={canEditFiles}
        actions={fileActions}
        downloadResult={downloadResult}
      />

      <BatchLockedVersions
        batch={batch}
        activeSupplierVersion={activeSupplierVersion}
        canRefreshSupplierVersion={Boolean(canRefreshSupplierVersion)}
        action={action}
        refreshSupplierVersion={refreshSupplierVersion}
      />

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
    </BatchWorkbench>
  );
}

function BatchWorkbench({
  selfOperated,
  notice,
  taskContent,
  children
}: {
  selfOperated: boolean;
  notice: ReactNode;
  taskContent: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`page-shell batch-workbench${selfOperated ? "" : " delivery-batch-detail"}`}>
      {notice}
      {selfOperated ? (
        taskContent
      ) : (
        <section className="delivery-batch-task" aria-label="当前批次任务">
          {taskContent}
        </section>
      )}
      {children}
    </div>
  );
}
