import { type ReactNode } from "react";
import { Card, Empty, Tabs } from "antd";
import type { ExceptionReview } from "./useExceptionReview";
import type { Batch } from "../../types";
import DeliveryImportRows from "./DeliveryImportRows";
import { useImportRowCount } from "./useImportRowCount";

export default function DeliveryDetailTabs({
  batch,
  computed,
  activeKey,
  onChange,
  reviewStats,
  fileCount,
  files,
  versions,
  review
}: {
  batch: Batch;
  computed: boolean;
  activeKey?: string;
  onChange: (key: string) => void;
  reviewStats?: ExceptionReview["reviewStats"];
  fileCount: number;
  files: ReactNode;
  versions: ReactNode;
  review: ReactNode;
}) {
  const importCount = useImportRowCount(batch, computed);
  const selected = activeKey ?? "review";
  return (
    <Card className="delivery-detail-tabs" classNames={{ body: "delivery-detail-tabs-body" }}>
      <Tabs
        activeKey={selected}
        onChange={onChange}
        items={[
          {
            key: "review",
            label: (
              <span>
                待办 <span className="pending-value">{computed ? (reviewStats?.unfinishedCount ?? "—") : "—"}</span>
              </span>
            ),
            children: computed ? review : <Empty description="预检并计算后显示待办" />
          },
          {
            key: "imports",
            label: `可导入 ${computed ? (importCount ?? "—") : "—"}`,
            children: computed ? (
              <DeliveryImportRows key={batch.id} batch={batch} />
            ) : (
              <Empty description="计算后显示可导入明细" />
            )
          },
          { key: "files", label: `来源文件 ${fileCount}`, children: files },
          { key: "versions", label: "锁定资料", children: versions }
        ]}
      />
    </Card>
  );
}
