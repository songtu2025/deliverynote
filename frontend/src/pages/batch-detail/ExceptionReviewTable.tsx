import InboundExceptionActions from "./InboundExceptionActions";
import { REVIEW_PAGE_SIZE } from "../../batchDetailApi";
import { Button, Card, Empty, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import type { Ref } from "react";
import { createPortal } from "react-dom";
import type { Batch, BatchFile, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { useExceptionTransfer } from "./useExceptionTransfer";
import ExceptionTransfers from "./ExceptionTransfers";
import type { ExceptionReview } from "./useExceptionReview";
import { ExceptionReason, ExceptionEvidence, ExceptionStatusTag, formatPositionValue } from "./ExceptionEvidence";
import { candidateSites } from "./reviewDraft";
import ExceptionReviewToolbar from "./ExceptionReviewToolbar";

export default function ExceptionReviewTable({
  selfOperated,
  review,
  fileById,
  hasOverreceiptRule,
  onOpen,
  onReset,
  sectionRef,
  transferBatch,
  onOpenDeliveryBatch,
  transferActionTarget,
  onSaved
}: {
  selfOperated: boolean;
  review: ExceptionReview;
  fileById: Record<number, BatchFile>;
  hasOverreceiptRule: boolean;
  onOpen: (record: DeliveryException) => void;
  onReset: () => void;
  sectionRef: Ref<HTMLDivElement>;
  transferBatch?: Batch;
  onOpenDeliveryBatch?: (id: number) => void;
  transferActionTarget?: HTMLElement | null;
  onSaved?: () => Promise<unknown>;
}) {
  const { exceptionTotal, exceptionsLoading, exceptions, reviewPage, setReviewPage } = review;
  const transfer = useExceptionTransfer(transferBatch, onOpenDeliveryBatch);
  return (
    <div ref={sectionRef} tabIndex={-1} className="review-section-anchor">
      <Card
        variant="borderless"
        className="section-card exception-review-card"
        classNames={{ body: "batch-detail-panel-body" }}
      >
        {review.reviewStats.unfinishedCount > 0 &&
          transferActionTarget &&
          createPortal(transfer.action, transferActionTarget)}
        <ExceptionReviewToolbar
          selfOperated={selfOperated}
          review={review}
          onReset={() => {
            transfer.reset();
            onReset();
          }}
        />
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
            emptyText: <Empty description={reviewEmptyText(review)} />
          }}
          columns={[
            ...reviewIdentityColumns(selfOperated, fileById),
            ...reviewDetailColumns(selfOperated, hasOverreceiptRule, onOpen).map((column) =>
              selfOperated && transferBatch && column.title === "操作"
                ? {
                    ...column,
                    width: 330,
                    fixed: "right" as const,
                    render: (_: unknown, record: DeliveryException) => (
                      <InboundExceptionActions
                        batch={transferBatch}
                        record={record}
                        supplierCode={fileById[record.batch_file_id]?.supplier_code ?? ""}
                        onOpen={onOpen}
                        onTransfer={(row) => transfer.openRow?.(row)}
                        onSaved={async () => {
                          await onSaved?.();
                        }}
                      />
                    )
                  }
                : column
            )
          ]}
        />
        {transfer.modal}
      </Card>
    </div>
  );
}

function reviewEmptyText({ reviewStats, reviewScope, exceptionsLoading }: ExceptionReview) {
  if (exceptionsLoading) return "正在读取审校记录";
  if (!reviewStats.totalCount) return "没有待处理，可以直接生成结果";
  return reviewScope === "unfinished" ? "审校已全部完成" : "没有匹配的审校记录";
}

function reviewIdentityColumns(
  selfOperated: boolean,
  fileById: Record<number, BatchFile>
): TableColumnsType<DeliveryException> {
  return [
    {
      title: selfOperated ? "来源文件" : "文件",
      dataIndex: "batch_file_id",
      width: selfOperated ? 130 : 56,
      ellipsis: true,
      render: (fileId: number) => {
        const file = fileById[fileId];
        const name = file?.original_name ?? `文件 #${fileId}`;
        return selfOperated ? (
          name
        ) : (
          <span title={name}>{file?.file_order != null ? String(file.file_order).padStart(2, "0") : name}</span>
        );
      }
    },
    {
      title: selfOperated ? "SKU" : "SKU / 站点",
      dataIndex: "sku",
      width: selfOperated ? 130 : 160,
      render: (value: string, record: DeliveryException) => (
        <>
          <span className="exception-identifier-value exception-sku-value">{value || "—"}</span>
          {!selfOperated && (
            <span
              className="exception-identifier-value exception-site-value exception-site-secondary"
              title={record.full_site}
            >
              {record.full_site.includes("、")
                ? `${candidateSites(record.full_site).length} 个候选站点`
                : record.full_site || "—"}
            </span>
          )}
        </>
      )
    },
    ...(selfOperated
      ? [
          {
            title: "站点",
            dataIndex: "full_site",
            width: 190,
            render: (value: string) => (
              <span className="exception-identifier-value exception-site-value">{value || "—"}</span>
            )
          }
        ]
      : []),
    { title: selfOperated ? "入库仓" : "目的仓", dataIndex: "destination", width: 100, ellipsis: true },
    ...(!selfOperated
      ? [
          {
            title: "定位",
            dataIndex: "scale_position",
            width: 100,
            render: (value: string | number, record: DeliveryException) => (
              <div className="exception-position-cell">
                <span>{formatPositionValue(value)}</span>
                <span>{formatPositionValue(record.stocking_position)}</span>
              </div>
            )
          }
        ]
      : [])
  ];
}

function reviewDetailColumns(
  selfOperated: boolean,
  hasOverreceiptRule: boolean,
  onOpen: (record: DeliveryException) => void
): TableColumnsType<DeliveryException> {
  return [
    {
      title: selfOperated ? "待处理量" : "待处理",
      dataIndex: "manual_quantity",
      width: 75,
      align: selfOperated ? undefined : "right",
      render: (value: number, record) => (
        <strong className="pending-value">{selfOperated ? remainingTransferQuantity(record) : value}</strong>
      )
    },
    {
      title: selfOperated ? "异常原因" : "原因",
      dataIndex: "reason",
      width: selfOperated ? 130 : 120,
      render: (reason: string) =>
        selfOperated ? <ExceptionReason reason={reason} /> : <Tag className="exception-reason-tag">{reason}</Tag>
    },
    {
      title: "审校依据",
      width: selfOperated ? 250 : 180,
      render: (_, record) => (
        <>
          <ExceptionEvidence exception={record} hasOverreceiptRule={hasOverreceiptRule} />
          {selfOperated && <ExceptionTransfers record={record} />}
        </>
      )
    },
    {
      title: "状态",
      dataIndex: "status",
      width: selfOperated ? 70 : 80,
      render: (value: string) => <ExceptionStatusTag status={value} selfOperated={selfOperated} />
    },
    {
      title: "操作",
      width: selfOperated ? 100 : 80,
      render: (_, record) =>
        !selfOperated && record.allowed_actions.length === 0 ? (
          <Typography.Text type="secondary">待处理</Typography.Text>
        ) : (
          <Button
            type={selfOperated ? "link" : record.status === "resolved" ? "text" : "primary"}
            size={selfOperated ? undefined : "small"}
            autoInsertSpace={selfOperated}
            aria-label={selfOperated ? undefined : `${record.status === "resolved" ? "修改" : "审校"} ${record.sku}`}
            onClick={() => onOpen(record)}
          >
            {selfOperated ? "查看并处理" : record.status === "resolved" ? "修改" : "审校"}
          </Button>
        )
    }
  ];
}
