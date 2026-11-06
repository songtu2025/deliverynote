import { Button, Typography } from "antd";
import type { TableColumnsType } from "antd";
import type { BatchFile, DeliveryException } from "../../types";
import { remainingTransferQuantity } from "../../exceptionTransferApi";
import { ExceptionReason, ExceptionEvidence, ExceptionStatusTag, formatPositionValue } from "./ExceptionEvidence";
import ExceptionTransfers from "./ExceptionTransfers";
import { candidateSites } from "./reviewDraft";
import InboundExceptionActions from "./InboundExceptionActions";
import type { InboundAdjustments } from "./useInboundAdjustments";

export function reviewIdentityColumns(
  selfOperated: boolean,
  fileById: Record<number, BatchFile>,
  onOpen: (record: DeliveryException) => void,
  adjustments: InboundAdjustments,
  onVersions?: () => void
): TableColumnsType<DeliveryException> {
  // 交货与自营仓共用「SKU / 站点」列：SKU 下依次显示来源文件序号与站点，自营仓再接站点选择等调整控件。
  return [
    {
      title: "SKU / 站点",
      dataIndex: "sku",
      width: selfOperated ? 230 : 160,
      render: (value: string, record: DeliveryException) => (
        <>
          <Button type="link" className="exception-sku-link" onClick={() => onOpen(record)}>
            {value || "—"}
          </Button>
          <ReviewSource record={record} fileById={fileById} />
          <span
            className="exception-identifier-value exception-site-value exception-site-secondary"
            title={record.full_site}
          >
            {record.full_site.includes("、")
              ? `${candidateSites(record.full_site).length} 个候选站点`
              : record.full_site || "—"}
          </span>
          {selfOperated && (
            <InboundExceptionActions
              placement="site"
              record={record}
              onOpen={onOpen}
              adjustments={adjustments}
              onVersions={onVersions}
            />
          )}
        </>
      )
    },
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

export function reviewDetailColumns(
  selfOperated: boolean,
  hasOverreceiptRule: boolean,
  onOpen: (record: DeliveryException) => void,
  fileById: Record<number, BatchFile>
): TableColumnsType<DeliveryException> {
  return [
    {
      title: "待处理",
      dataIndex: "manual_quantity",
      width: 75,
      align: "right",
      render: (value: number, record) => (
        <strong className="pending-value">{selfOperated ? remainingTransferQuantity(record) : value}</strong>
      )
    },
    {
      title: "原因与依据",
      width: selfOperated ? 320 : 280,
      render: (_, record) => (
        <div className="exception-reason-evidence">
          <ExceptionReason reason={record.reason} />
          <ExceptionEvidence
            exception={record}
            hasOverreceiptRule={hasOverreceiptRule}
            documentNote={fileById[record.batch_file_id]?.document_note}
          />
          {selfOperated && <ExceptionTransfers record={record} />}
        </div>
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
        selfOperated ? null : record.allowed_actions.length === 0 ? (
          <Typography.Text type="secondary">待处理</Typography.Text>
        ) : (
          <Button
            type="link"
            size="small"
            autoInsertSpace={false}
            aria-label={`${record.status === "resolved" ? "修改" : "审校"} ${record.sku}`}
            onClick={() => onOpen(record)}
          >
            {record.status === "resolved" ? "修改" : "审校"}
          </Button>
        )
    }
  ];
}

function ReviewSource({ record, fileById }: { record: DeliveryException; fileById: Record<number, BatchFile> }) {
  if (Object.keys(fileById).length < 2) return null;
  const file = fileById[record.batch_file_id];
  return (
    <span className="exception-source-meta" title={file?.original_name}>
      文件 {file?.file_order ?? record.batch_file_id}
    </span>
  );
}
