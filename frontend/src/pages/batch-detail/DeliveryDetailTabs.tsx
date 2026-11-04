import type { ReactNode } from "react";
import { Card, Tabs } from "antd";
import type { ExceptionReview } from "./useExceptionReview";
import type { Batch } from "../../types";
import DeliveryImportRows from "./DeliveryImportRows";

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
  const selected = computed ? (activeKey ?? "review") : activeKey === "versions" ? "versions" : "files";
  return (
    <Card className="delivery-detail-tabs" classNames={{ body: "delivery-detail-tabs-body" }}>
      <Tabs
        activeKey={selected}
        onChange={onChange}
        items={[
          ...(computed
            ? [
                { key: "review", label: `待处理 ${reviewStats?.unfinishedCount ?? "—"}`, children: review },
                {
                  key: "imports",
                  label: `可导入 ${batch.summary?.import_total ?? "—"}`,
                  children: <DeliveryImportRows key={batch.id} batch={batch} />
                }
              ]
            : []),
          { key: "files", label: `来源文件 ${fileCount}`, children: files },
          { key: "versions", label: "锁定资料", children: versions }
        ]}
      />
    </Card>
  );
}
