import { REVIEW_PAGE_SIZE } from "../../batchDetailApi";
import { Descriptions, Drawer, Tag } from "antd";
import type { Batch, BatchFile, DeliveryException } from "../../types";
import type { ExceptionEditor } from "./useExceptionEditor";
import { ExceptionStatusTag, PositionValue } from "./ExceptionEvidence";
import ReasonGuidance from "./ReasonGuidance";
import ExceptionReviewActions from "./ExceptionReviewActions";
import SplitPartsForm from "./SplitPartsForm";
import SelfOperatedExceptionDetails from "./SelfOperatedExceptionDetails";

export default function ExceptionReviewDrawer({
  editor,
  batch,
  fileById,
  action
}: {
  editor: ExceptionEditor;
  batch: Batch;
  fileById: Record<number, BatchFile>;
  action: string | null;
}) {
  const { splitTarget, setSplitTarget, currentReviewIndex, reviewPage, exceptionTotal } = editor;
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <Drawer
      title={
        <div className="review-drawer-title">
          <strong>审校处理 · {splitTarget?.sku ?? ""}</strong>
          {currentReviewIndex >= 0 && (
            <span>
              第 {(reviewPage - 1) * REVIEW_PAGE_SIZE + currentReviewIndex + 1} / {exceptionTotal} 条
            </span>
          )}
        </div>
      }
      size={selfOperated ? "min(1280px, 100vw)" : 520}
      open={splitTarget !== null}
      onClose={() => setSplitTarget(null)}
      extra={splitTarget ? <ExceptionStatusTag status={splitTarget.status} /> : null}
      footer={<ExceptionReviewActions editor={editor} action={action} />}
    >
      {splitTarget && (
        <>
          <ExceptionSourceSummary selfOperated={selfOperated} splitTarget={splitTarget} fileById={fileById} />

          {selfOperated ? (
            <SelfOperatedExceptionDetails
              exception={splitTarget}
              supplierCode={fileById[splitTarget.batch_file_id].supplier_code}
            />
          ) : (
            <ReasonGuidance exception={splitTarget} hasOverreceiptRule={Boolean(batch.overreceipt_rule)} />
          )}

          {!selfOperated && <SplitPartsForm editor={editor} />}
        </>
      )}
    </Drawer>
  );
}

function ExceptionSourceSummary({
  selfOperated,
  splitTarget,
  fileById
}: {
  selfOperated: boolean;
  splitTarget: DeliveryException;
  fileById: Record<number, BatchFile>;
}) {
  return (
    <Descriptions className="split-source" size="small" column={1}>
      <Descriptions.Item label="来源文件">{fileById[splitTarget.batch_file_id]?.original_name}</Descriptions.Item>
      {selfOperated && (
        <Descriptions.Item label="供应商">
          {fileById[splitTarget.batch_file_id]?.supplier_name || "—"}
        </Descriptions.Item>
      )}
      <Descriptions.Item label="站点">{splitTarget.full_site || "—"}</Descriptions.Item>
      <Descriptions.Item label={selfOperated ? "入库仓" : "目的仓"}>{splitTarget.destination || "—"}</Descriptions.Item>
      {!selfOperated && (
        <>
          <Descriptions.Item label="规模定位">
            <PositionValue value={splitTarget.scale_position} />
          </Descriptions.Item>
          <Descriptions.Item label="备货定位">
            <PositionValue value={splitTarget.stocking_position} />
          </Descriptions.Item>
        </>
      )}
      <Descriptions.Item label="异常原因">
        <Tag color="warning">{splitTarget.reason}</Tag>
      </Descriptions.Item>
    </Descriptions>
  );
}
