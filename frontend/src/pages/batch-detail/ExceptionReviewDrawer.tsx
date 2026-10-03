import { Descriptions, Drawer, Form, Radio, Tag } from "antd";
import type { Batch, BatchFile, DeliveryException } from "../../types";
import type { ExceptionEditor } from "./useExceptionEditor";
import { ExceptionStatusTag, PositionValue } from "./ExceptionEvidence";
import ReasonGuidance from "./ReasonGuidance";
import ExceptionReviewActions from "./ExceptionReviewActions";
import SplitPartsForm from "./SplitPartsForm";

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
  const {
    splitTarget,
    setSplitTarget,
    currentReviewIndex,
    reviewPage,
    exceptionTotal,
    selfOperatedSiteSelection,
    splitForm,
    setReviewDirty,
    splitCandidateSites
  } = editor;
  const selfOperated = batch.workflow === "self_operated_inbound";
  return (
    <Drawer
      title={
        <div className="review-drawer-title">
          <strong>审校处理 · {splitTarget?.sku ?? ""}</strong>
          {currentReviewIndex >= 0 && (
            <span>
              第 {(reviewPage - 1) * 10 + currentReviewIndex + 1} / {exceptionTotal} 条
            </span>
          )}
        </div>
      }
      size={520}
      open={splitTarget !== null}
      onClose={() => setSplitTarget(null)}
      extra={splitTarget ? <ExceptionStatusTag status={splitTarget.status} /> : null}
      footer={<ExceptionReviewActions editor={editor} action={action} />}
    >
      {splitTarget && (
        <>
          <ExceptionSourceSummary splitTarget={splitTarget} fileById={fileById} />

          <ReasonGuidance
            exception={splitTarget}
            hasOverreceiptRule={Boolean(selfOperated ? batch.self_operated_overreceipt_rule : batch.overreceipt_rule)}
            selfOperated={selfOperated}
          />

          {selfOperatedSiteSelection ? (
            <Form form={splitForm} layout="vertical" onValuesChange={() => setReviewDirty(true)}>
              <Form.Item
                name={["parts", 0, "site"]}
                label="选择正确的完整站点"
                rules={[{ required: true, message: "请选择一个候选站点" }]}
              >
                <Radio.Group className="candidate-site-options">
                  {splitCandidateSites.map((site) => (
                    <Radio key={site} value={site}>
                      {site}
                    </Radio>
                  ))}
                </Radio.Group>
              </Form.Item>
            </Form>
          ) : (
            <SplitPartsForm editor={editor} />
          )}
        </>
      )}
    </Drawer>
  );
}

function ExceptionSourceSummary({
  splitTarget,
  fileById
}: {
  splitTarget: DeliveryException;
  fileById: Record<number, BatchFile>;
}) {
  return (
    <Descriptions className="split-source" size="small" column={1}>
      <Descriptions.Item label="来源文件">{fileById[splitTarget.batch_file_id]?.original_name}</Descriptions.Item>
      <Descriptions.Item label="站点">{splitTarget.full_site || "—"}</Descriptions.Item>
      <Descriptions.Item label="目的仓">{splitTarget.destination || "—"}</Descriptions.Item>
      <Descriptions.Item label="规模定位">
        <PositionValue value={splitTarget.scale_position} />
      </Descriptions.Item>
      <Descriptions.Item label="备货定位">
        <PositionValue value={splitTarget.stocking_position} />
      </Descriptions.Item>
      <Descriptions.Item label="异常原因">
        <Tag color="warning">{splitTarget.reason}</Tag>
      </Descriptions.Item>
    </Descriptions>
  );
}
