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
  selfOperated,
  review,
  fileById,
  hasOverreceiptRule,
  onOpen,
  onReset,
  sectionRef
}: {
  selfOperated: boolean;
  review: ExceptionReview;
  fileById: Record<number, BatchFile>;
  hasOverreceiptRule: boolean;
  onOpen: (record: DeliveryException) => void;
  onReset: () => void;
  sectionRef: Ref<HTMLDivElement>;
}) {
  const { reviewStats, exceptionTotal, exceptionsLoading, exceptions, reviewPage, setReviewPage } = review;
  return (
    <div ref={sectionRef} tabIndex={-1} className="review-section-anchor">
      <Card
        title={selfOperated ? undefined : `待处理审校（共 ${reviewStats.totalCount} 条）`}
        extra={!selfOperated && <span className="toolbar-count">当前显示 {exceptionTotal} 条</span>}
        className="section-card exception-review-card"
        classNames={{ body: "batch-detail-panel-body" }}
        loading={exceptionsLoading && !selfOperated}
      >
        <ExceptionReviewToolbar selfOperated={selfOperated} review={review} onReset={onReset} />
        <Table<DeliveryException>
          rowKey="id"
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
          scroll={{ x: selfOperated ? 1175 : 1260 }}
          locale={{
            emptyText: <Empty description={reviewEmptyText(review)} />
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
            { title: selfOperated ? "入库仓" : "目的仓", dataIndex: "destination", width: 100, ellipsis: true },
            ...(!selfOperated
              ? [
                  {
                    title: "规模定位",
                    dataIndex: "scale_position",
                    width: 85,
                    ellipsis: true,
                    render: (value: string | number, record: DeliveryException) => (
                      <Tooltip title={`备货定位：${formatPositionValue(record.stocking_position)}`}>
                        <span>
                          <PositionValue value={value} />
                        </span>
                      </Tooltip>
                    )
                  }
                ]
              : []),
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
                !selfOperated && record.allowed_actions.length === 0 ? (
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

function reviewEmptyText({ reviewStats, reviewScope, exceptionsLoading }: ExceptionReview) {
  if (exceptionsLoading) return "正在读取审校记录";
  if (!reviewStats.totalCount) return "本批次没有待处理记录";
  return reviewScope === "unfinished" ? "当前没有未完成记录" : "没有匹配的审校记录";
}
