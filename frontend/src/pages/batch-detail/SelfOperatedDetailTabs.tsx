import DeliveryImportRows from "./DeliveryImportRows";
import { useImportRowCount } from "./useImportRowCount";
import type { ReactNode } from "react";
import { Card, Empty, Tabs } from "antd";
import type { Batch } from "../../types";
import { batchPresentation } from "./batchPresentation";
import type { ExceptionReview } from "./useExceptionReview";

type DetailTabsProps = {
  batch: Batch;
  activeKey?: string;
  onChange: (key: string) => void;
  reviewStats?: ExceptionReview["reviewStats"];
  files: ReactNode;
  versions: ReactNode;
  receipts: ReactNode;
  receiptTodos: ReactNode;
  review: ReactNode;
};

export default function SelfOperatedDetailTabs(props: DetailTabsProps) {
  const { batch, activeKey, onChange } = props;
  const { computed } = batchPresentation(batch);
  const importCount = useImportRowCount(batch, computed);
  const selected = activeKey ?? "review";
  return (
    <Card className="self-operated-detail-tabs" classNames={{ body: "delivery-detail-tabs-body" }}>
      <Tabs
        classNames={{ header: "batch-workspace-tabs-nav" }}
        activeKey={selected}
        onChange={onChange}
        items={workspaceItems(props, computed, importCount)}
      />
    </Card>
  );
}

function workspaceItems(props: DetailTabsProps, computed: boolean, importCount?: number) {
  const { batch, reviewStats, review, receipts, receiptTodos, files, versions } = props;
  const counts = workspaceCounts(batch, reviewStats, computed);
  return [
    {
      key: "review",
      label: (
        <span>
          待处理 <span className="pending-value">{counts.todo}</span>
        </span>
      ),
      destroyOnHidden: true,
      children: computed ? review : receiptTodoContent(batch, receiptTodos)
    },
    {
      key: "imports",
      label: `可入库 ${computed ? (importCount ?? "—") : "—"}`,
      children: computed ? (
        <DeliveryImportRows key={batch.id} batch={batch} />
      ) : (
        <Empty description="计算后显示可入库明细" />
      )
    },
    {
      key: "receipts",
      label: (
        <span>累计实收核对{counts.receipts ? <span className="pending-value"> {counts.receipts}</span> : null}</span>
      ),
      children: receipts
    },
    { key: "files", label: `来源文件 ${counts.files}`, children: files },
    { key: "versions", label: "锁定资料", children: versions }
  ];
}

function workspaceCounts(batch: Batch, stats: DetailTabsProps["reviewStats"], computed: boolean) {
  const reviewCounts = computed && stats ? stats : { unfinishedCount: "—", resolvedCount: "—" };
  // 标签只在有待核对项时显示数量，避免 0 被误读为没有核对数据。
  const receipts = batch.receipt?.issue_count ?? 0;
  return {
    todo: computed ? reviewCounts.unfinishedCount : receipts,
    receipts,
    files: batch.files?.length ?? 0
  };
}

function receiptTodoContent(batch: Batch, content: ReactNode) {
  return batch.receipt?.issue_count ? content : <Empty description="预检后显示待核对项" />;
}
