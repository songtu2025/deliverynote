import type { ReactNode } from "react";
import { Alert, Button, Card, Descriptions, Flex, Table, Typography } from "antd";
import { formatBeijingDateTime } from "../../dateTime";
import type { DeliveryException } from "../../types";
import type { InboundAllocation, PurchaseOption } from "../../inboundExceptionApi";
import { useInboundExceptionDetails } from "./useInboundExceptionDetails";

export default function SelfOperatedExceptionDetails({
  exception,
  supplierCode
}: {
  exception: DeliveryException;
  supplierCode: string;
}) {
  const { purchases, allocations } = useInboundExceptionDetails(exception.id, supplierCode, exception.sku);
  return (
    <Flex vertical gap="middle">
      <Descriptions
        aria-label="当前异常数量"
        size="small"
        column={{ xs: 2, sm: 4 }}
        items={[
          { key: "requested", label: "本次申请", children: exception.delivery_quantity },
          { key: "normal", label: "正常分配", children: exception.purchase_allocated_quantity ?? "—" },
          { key: "over", label: "规则内超收", children: exception.overreceipt_allocated_quantity ?? "—" },
          {
            key: "pending",
            label: "待处理",
            children: <strong className="pending-value">{exception.manual_quantity}</strong>
          }
        ]}
      />
      <PurchaseEvidence state={purchases} />
      <AllocationEvidence state={allocations} />
    </Flex>
  );
}

type Evidence = ReturnType<typeof useInboundExceptionDetails>;

function PurchaseEvidence({ state: purchases }: { state: Evidence["purchases"] }) {
  return (
    <EvidenceSection title="未交采购明细" state={purchases}>
      <Typography.Paragraph type="secondary">
        使用整批采购快照，展示同一供应商、同一 SKU 的各站点未交需求，不改变本批分配。
        {purchases.data && ` 采购数据更新于：${formatBeijingDateTime(purchases.data.queried_at ?? "")}`}
      </Typography.Paragraph>
      <Table<PurchaseOption>
        size="small"
        rowKey="id"
        loading={purchases.loading}
        dataSource={purchases.data?.items ?? []}
        scroll={{ x: 650 }}
        pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
        locale={{ emptyText: purchases.loading ? "正在查询未交采购明细" : "未查询到该供应商与 SKU 的未交采购明细" }}
        columns={[
          { title: "PO 单号", dataIndex: "po_code", width: 180 },
          { title: "完整站点", dataIndex: "site", width: 210, render: showValue },
          { title: "目的仓", dataIndex: "warehouse", width: 160, render: showValue },
          { title: "未交数量", dataIndex: "remaining_quantity", width: 100, align: "right" }
        ]}
      />
    </EvidenceSection>
  );
}

function AllocationEvidence({ state: allocations }: { state: Evidence["allocations"] }) {
  return (
    <EvidenceSection title="本次入库分配明细" retryLabel="重新读取分配" state={allocations}>
      <Typography.Paragraph type="secondary">
        当前来源文件、SKU 和站点的计算结果。“本次分配”表示可生成入库导入文件，不代表 ERP 已完成入库。
        {allocations.data && ` 批次更新：${formatBeijingDateTime(allocations.data.batch_updated_at)}`}
        {allocations.data?.history_captured_at &&
          `；历史快照：${formatBeijingDateTime(allocations.data.history_captured_at)}`}
      </Typography.Paragraph>
      <Table<InboundAllocation>
        size="small"
        rowKey="id"
        loading={allocations.loading}
        dataSource={allocations.data?.items ?? []}
        scroll={{ x: 1180 }}
        pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
        locale={{
          emptyText: allocations.loading ? "正在读取本次分配明细" : "当前文件的该 SKU 在此站点暂无可入库分配"
        }}
        columns={[
          { title: "PO 单号", dataIndex: "po_code", width: 150, render: showValue },
          { title: "关联交货单", dataIndex: "delivery_no", width: 150, render: showValue },
          { title: "入库单号", dataIndex: "inbound_no", width: 150, render: showValue },
          { title: "完整站点", dataIndex: "site", width: 190, render: showValue },
          { title: "入库仓", dataIndex: "warehouse", width: 140, render: showValue },
          { title: "历史已入库", dataIndex: "history_quantity", width: 100, align: "right", render: showValue },
          { title: "正常分配", dataIndex: "normal_quantity", width: 100, align: "right", render: showValue },
          { title: "规则内超收", dataIndex: "overreceipt_quantity", width: 100, align: "right", render: showValue },
          { title: "本次分配", dataIndex: "current_quantity", width: 100, align: "right", render: showValue }
        ]}
      />
    </EvidenceSection>
  );
}

const showValue = (value: string | number | null) => value ?? "—";

function EvidenceSection({
  title,
  retryLabel,
  state,
  children
}: {
  title: string;
  retryLabel?: string;
  state: { loading: boolean; error: string | null; retry?: () => void };
  children: ReactNode;
}) {
  return (
    <section aria-label={title}>
      <Card
        size="small"
        title={title}
        extra={
          retryLabel && (
            <Button size="small" disabled={state.loading} onClick={state.retry}>
              {retryLabel}
            </Button>
          )
        }
      >
        {state.error ? <Alert type="error" showIcon title={state.error} /> : children}
      </Card>
    </section>
  );
}
