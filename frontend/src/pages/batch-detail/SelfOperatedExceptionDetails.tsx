import type { ReactNode } from "react";
import { Alert, Button, Card, Descriptions, Flex, Table, Typography } from "antd";
import { formatBeijingDateTime } from "../../dateTime";
import type { Batch, DeliveryException } from "../../types";
import type { InboundAllocations, PurchaseOption } from "../../inboundExceptionApi";
import { useInboundExceptionDetails } from "./useInboundExceptionDetails";
import ReasonGuidance from "./ReasonGuidance";
import InboundAllocationEditor from "./InboundAllocationEditor";
import { useInboundRecalculation } from "./useInboundRecalculation";
import { PURCHASE_LOADING_MESSAGE } from "./BatchPurchaseSnapshot";

export default function SelfOperatedExceptionDetails({
  exception,
  supplierCode,
  batch,
  onSaved
}: {
  exception: DeliveryException;
  supplierCode: string;
  batch?: Batch;
  onSaved?: () => Promise<unknown>;
}) {
  const { purchases, allocations } = useInboundExceptionDetails(
    exception.id,
    supplierCode,
    exception.sku,
    batch ? exception : undefined
  );
  const recalculation = useInboundRecalculation({ batch, data: allocations.data, reload: allocations.reload, onSaved });
  const quantities = currentQuantities(exception, allocations.data);
  return (
    <Flex vertical gap="middle">
      <ReasonGuidance
        exception={exception}
        hasOverreceiptRule={Boolean(batch?.self_operated_overreceipt_rule)}
        selfOperated
      />
      {recalculation.busy && <Alert type="info" showIcon title="正在重算整批，完成后自动刷新" />}
      {recalculation.feedback && (
        <Alert type={recalculation.feedback.error ? "error" : "success"} showIcon title={recalculation.feedback.text} />
      )}
      <Descriptions
        aria-label="当前异常数量"
        size="small"
        column={{ xs: 2, sm: 4 }}
        items={[
          { key: "requested", label: "本次申请", children: exception.delivery_quantity },
          { key: "normal", label: "正常分配", children: quantities.normal },
          { key: "over", label: "规则内超收", children: quantities.over },
          {
            key: "pending",
            label: "待处理",
            children: <strong className="pending-value">{quantities.pending}</strong>
          }
        ]}
      />
      <PurchaseEvidence state={purchases} />
      <AllocationEvidence
        state={allocations}
        exception={exception}
        onSaved={recalculation.saved}
        locked={recalculation.busy}
      />
    </Flex>
  );
}

type Evidence = ReturnType<typeof useInboundExceptionDetails>;

function currentQuantities(exception: DeliveryException, data: InboundAllocations | null) {
  if (!data)
    return {
      normal: exception.purchase_allocated_quantity ?? "—",
      over: exception.overreceipt_allocated_quantity ?? "—",
      pending: exception.manual_quantity
    };
  return {
    normal: data.items.reduce((total, row) => total + (row.normal_quantity ?? 0), 0),
    over: data.items.reduce((total, row) => total + (row.overreceipt_quantity ?? 0), 0),
    pending: data.remaining_quantity ?? exception.manual_quantity
  };
}

function PurchaseEvidence({ state: purchases }: { state: Evidence["purchases"] }) {
  return (
    <EvidenceSection title="未交采购明细" state={purchases}>
      {purchases.loading && <Typography.Paragraph role="status">{PURCHASE_LOADING_MESSAGE}</Typography.Paragraph>}
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
        locale={{ emptyText: purchases.loading ? "" : "未查询到该供应商与 SKU 的未交采购明细" }}
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

function AllocationEvidence({
  state: allocations,
  exception,
  locked,
  onSaved
}: {
  state: Evidence["allocations"];
  exception: DeliveryException;
  locked: boolean;
  onSaved?: () => Promise<unknown>;
}) {
  return (
    <EvidenceSection
      title="本次入库分配明细"
      retryLabel="重新读取分配"
      state={{ ...allocations, loading: allocations.loading || locked }}
    >
      <Typography.Paragraph type="secondary">
        当前来源文件、SKU 和站点的计算结果。“本次分配”表示可生成入库导入文件，不代表 ERP 已完成入库。
        {allocations.data && " 批次更新：" + formatBeijingDateTime(allocations.data.batch_updated_at)}
        {allocations.data?.history_captured_at &&
          "；历史快照：" + formatBeijingDateTime(allocations.data.history_captured_at)}
      </Typography.Paragraph>
      {allocations.data && (
        <InboundAllocationEditor
          key={exception.id + ":" + allocations.data.batch_updated_at}
          data={allocations.data}
          exception={exception}
          locked={locked}
          onSaved={onSaved}
        />
      )}
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
