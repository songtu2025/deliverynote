import InboundExceptionActions from "./InboundExceptionActions";
import { REVIEW_PAGE_SIZE } from "../../batchDetailApi";
import { Card, Empty, Flex, Table } from "antd";
import type { Ref } from "react";
import type { Batch, BatchFile, DeliveryException } from "../../types";
import { useExceptionTransfer } from "./useExceptionTransfer";
import type { ExceptionReview } from "./useExceptionReview";
import { reviewIdentityColumns, reviewDetailColumns } from "./exceptionReviewColumns";
import ExceptionReviewToolbar from "./ExceptionReviewToolbar";
import type { InboundAdjustments } from "./useInboundAdjustments";
import InboundAdjustmentActions from "./InboundAdjustmentActions";
import BatchManualAllowances from "./BatchManualAllowances";

export default function ExceptionReviewTable({
  selfOperated,
  review,
  adjustments,
  fileById,
  hasOverreceiptRule,
  onOpen,
  onReset,
  sectionRef,
  transferBatch,
  onOpenDeliveryBatch,
  onVersions,
  onSaved
}: {
  selfOperated: boolean;
  review: ExceptionReview;
  adjustments: InboundAdjustments;
  fileById: Record<number, BatchFile>;
  hasOverreceiptRule: boolean;
  onOpen: (record: DeliveryException) => void;
  onReset: () => void;
  sectionRef: Ref<HTMLDivElement>;
  transferBatch?: Batch;
  onOpenDeliveryBatch?: (id: number) => void;
  onVersions?: () => void;
  onSaved?: () => Promise<unknown>;
}) {
  const { exceptionTotal, exceptionsLoading, exceptions, reviewPage, setReviewPage } = review;
  const transfer = useExceptionTransfer(transferBatch, onOpenDeliveryBatch, onSaved);
  const actions = selfOperated && (adjustments.count > 0 || transfer.action) && (
    <Flex className="table-toolbar" justify="end" align="center" gap="small" wrap>
      <InboundAdjustmentActions adjustments={adjustments} />
      {transfer.action}
    </Flex>
  );
  return (
    <div ref={sectionRef} tabIndex={-1} className="review-section-anchor">
      <Card
        variant="borderless"
        className="section-card exception-review-card"
        classNames={{ body: "batch-detail-panel-body" }}
      >
        <ExceptionReviewToolbar
          selfOperated={selfOperated}
          review={review}
          onReset={() => {
            transfer.reset();
            onReset();
          }}
        />
        {actions}
        <Table<DeliveryException>
          rowKey="id"
          rowSelection={transfer.rowSelection}
          loading={exceptionsLoading}
          size={selfOperated ? "small" : undefined}
          dataSource={exceptions}
          pagination={
            exceptionTotal > REVIEW_PAGE_SIZE
              ? {
                  current: reviewPage,
                  pageSize: REVIEW_PAGE_SIZE,
                  total: exceptionTotal,
                  showSizeChanger: false,
                  placement: selfOperated ? ["topEnd", "bottomEnd"] : ["bottomEnd"],
                  onChange: setReviewPage
                }
              : false
          }
          scroll={{ x: selfOperated ? 1175 : 980 }}
          onHeaderRow={() => ({ className: "exception-review-header" })}
          locale={{
            emptyText: <Empty description={reviewEmptyText(review, selfOperated)} />
          }}
          columns={[
            ...reviewIdentityColumns(selfOperated, fileById, onOpen, adjustments, onVersions),
            ...reviewDetailColumns(selfOperated, hasOverreceiptRule, onOpen, fileById).map((column) =>
              selfOperated && transferBatch && column.title === "操作"
                ? {
                    ...column,
                    title: "操作",
                    width: 130,
                    fixed: "right" as const,
                    render: (_: unknown, record: DeliveryException) => (
                      <InboundExceptionActions
                        placement="actions"
                        record={record}
                        onOpen={onOpen}
                        adjustments={adjustments}
                        onVersions={onVersions}
                      />
                    )
                  }
                : column
            )
          ]}
        />
        {selfOperated && transferBatch && <BatchManualAllowances batch={transferBatch} onSaved={onSaved} />}
        {transfer.modal}
      </Card>
    </div>
  );
}

function reviewEmptyText({ reviewStats, reviewScope, exceptionsLoading }: ExceptionReview, selfOperated: boolean) {
  if (selfOperated) {
    if (exceptionsLoading) return "正在读取待处理记录";
    if (!reviewStats.totalCount || reviewScope === "unfinished") return "没有待处理";
    return "没有匹配的处理记录";
  }
  if (exceptionsLoading) return "正在读取审校记录";
  if (!reviewStats.totalCount) return "没有待处理，可以直接生成结果";
  return reviewScope === "unfinished" ? "审校已全部完成" : "没有匹配的审校记录";
}
