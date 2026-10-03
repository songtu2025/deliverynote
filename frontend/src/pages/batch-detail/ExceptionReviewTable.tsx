import { REVIEW_PAGE_SIZE } from "../../batchDetailApi";
import { Button, Card, Empty, Table, Tooltip, Typography } from "antd";
import type { Ref } from "react";
import type { BatchFile, DeliveryException } from "../../types";
import type { ExceptionReview } from "./useExceptionReview";
import {
  ExceptionReason,
  ExceptionEvidence,
  ExceptionStatusTag,
  formatPositionValue,
  PositionValue
} from "./ExceptionEvidence";
import ExceptionReviewToolbar from "./ExceptionReviewToolbar";

export default function ExceptionReviewTable({
  review,
  fileById,
  hasOverreceiptRule,
  onOpen,
  onReset,
  sectionRef
}: {
  review: ExceptionReview;
  fileById: Record<number, BatchFile>;
  hasOverreceiptRule: boolean;
  onOpen: (record: DeliveryException) => void;
  onReset: () => void;
  sectionRef: Ref<HTMLDivElement>;
}) {
  const { reviewStats, exceptionTotal, exceptionsLoading, exceptions, reviewPage, setReviewPage, reviewScope } = review;
  return (
    <div ref={sectionRef} tabIndex={-1} className="review-section-anchor">
      <Card
        title={`待处理审校（共 ${reviewStats.totalCount} 条）`}
        extra={<span className="toolbar-count">当前显示 {exceptionTotal} 条</span>}
        className="section-card exception-review-card"
        loading={exceptionsLoading}
      >
        <ExceptionReviewToolbar review={review} onReset={onReset} />
        <Table<DeliveryException>
          rowKey="id"
          dataSource={exceptions}
          pagination={
            exceptionTotal > REVIEW_PAGE_SIZE
              ? {
                  current: reviewPage,
                  pageSize: REVIEW_PAGE_SIZE,
                  total: exceptionTotal,
                  showSizeChanger: false,
                  onChange: setReviewPage
                }
              : false
          }
          scroll={{ x: 1260 }}
          locale={{
            emptyText: (
              <Empty
                description={
                  reviewStats.totalCount
                    ? reviewScope === "unfinished"
                      ? "当前没有未完成记录"
                      : "没有匹配的审校记录"
                    : "本批次没有待处理记录"
                }
              />
            )
          }}
          columns={[
            {
              title: "来源文件",
              dataIndex: "batch_file_id",
              width: 130,
              ellipsis: true,
              render: (fileId: number) => fileById[fileId]?.original_name ?? `文件 #${fileId}`
            },
            {
              title: "SKU",
              dataIndex: "sku",
              width: 130,
              render: (value: string) => (
                <span className="exception-identifier-value exception-sku-value">{value || "—"}</span>
              )
            },
            {
              title: "站点",
              dataIndex: "full_site",
              width: 190,
              render: (value: string) => (
                <span className="exception-identifier-value exception-site-value">{value || "—"}</span>
              )
            },
            { title: "目的仓", dataIndex: "destination", width: 100, ellipsis: true },
            {
              title: "规模定位",
              dataIndex: "scale_position",
              width: 85,
              ellipsis: true,
              render: (value: string | number, record) => (
                <Tooltip title={`备货定位：${formatPositionValue(record.stocking_position)}`}>
                  <span>
                    <PositionValue value={value} />
                  </span>
                </Tooltip>
              )
            },
            {
              title: "待处理量",
              dataIndex: "manual_quantity",
              width: 75,
              render: (value: number) => <strong className="pending-value">{value}</strong>
            },
            {
              title: "异常原因",
              dataIndex: "reason",
              width: 130,
              render: (reason: string) => <ExceptionReason reason={reason} />
            },
            {
              title: "审校依据",
              width: 250,
              render: (_, record) => <ExceptionEvidence exception={record} hasOverreceiptRule={hasOverreceiptRule} />
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 70,
              render: (value: string) => <ExceptionStatusTag status={value} />
            },
            {
              title: "操作",
              width: 100,
              render: (_, record) =>
                record.allowed_actions.length === 0 ? (
                  <Typography.Text type="secondary">待处理</Typography.Text>
                ) : (
                  <Button type="link" onClick={() => onOpen(record)}>
                    查看并处理
                  </Button>
                )
            }
          ]}
        />
      </Card>
    </div>
  );
}
